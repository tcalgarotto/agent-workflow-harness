# SPDX-License-Identifier: Apache-2.0
"""Trusted Docker control, without host bind mounts or candidate Docker options."""
import io
from pathlib import Path
import threading
import tarfile
import time

import docker
from docker.errors import NotFound
from docker.types import LogConfig, Mount

from ..validation import contains, safe_path
from .artifacts import UnsafeExecution, check_tree, from_archive


class DockerBackend:
    def __init__(self, socket="/var/run/docker.sock"):
        if not Path(socket).is_absolute():
            raise UnsafeExecution("local_unix_socket_required")
        # Never inherit DOCKER_HOST, contexts, registry credentials or TCP options.
        self.client = docker.DockerClient(base_url="unix://" + socket, version="auto", timeout=3)

    def preflight(self, profile):
        info = self.client.info()
        if (info.get("OSType") != "linux" or info.get("CgroupVersion") != "2"
                or not all(info.get(k) for k in ["MemoryLimit", "SwapLimit", "PidsLimit", "CpuCfsQuota"])
                or not any("seccomp" in item for item in info.get("SecurityOptions", []))):
            raise UnsafeExecution("required_linux_controls_unavailable")
        if any("rootless" in item for item in info.get("SecurityOptions", [])):
            raise UnsafeExecution("rootless_daemon_not_conformant_for_tmpfs_volume_profile")
        image = self.client.images.get(profile.image)  # No implicit pull/build.
        if image.attrs["Config"].get("Volumes") or image.attrs["Config"].get("OnBuild"):
            raise UnsafeExecution("image_has_implicit_mounts_or_build_hooks")
        return {"image_id": image.id, "engine_version": self.client.version()["Version"],
                "daemon_rootless": any("rootless" in item for item in info.get("SecurityOptions", [])),
                "cgroup_version": info["CgroupVersion"]}

    def create(self, name, execution_id, manifest_hash, profile):
        volume_name = name + "-memory"
        labels = {"awh.m2a.execution": execution_id, "awh.m2a.manifest": manifest_hash}
        try:
            self.client.volumes.get(volume_name)
        except NotFound:
            pass
        else:
            raise UnsafeExecution("existing_volume_requires_recovery")
        self.client.volumes.create(name=volume_name, driver="local", labels=labels,
            driver_opts={"type": "tmpfs", "device": "tmpfs",
                         "o": f"size={profile.workspace_mb}m,mode=0555,uid=0,gid=0,nosuid,nodev,noexec"})
        container = self.client.containers.create(
            profile.image, entrypoint=["/usr/local/bin/python", "-I", "-u", "-c"],
            # Independent backstop if the host monitor dies while unpaused.
            command=[f"import time; time.sleep({profile.timeout_seconds + 10})"], name=name, hostname="awh",
            user="10001:10001", working_dir="/workspace", read_only=True,
            network_mode="none", network_disabled=True, ipc_mode="private", cgroupns="private",
            cap_drop=["ALL"], security_opt=["no-new-privileges:true"], init=True,
            mem_limit=profile.memory_mb * 1024 * 1024, memswap_limit=profile.memory_mb * 1024 * 1024,
            nano_cpus=profile.cpu_millis * 1_000_000, pids_limit=profile.pids,
            mounts=[Mount("/workspace", volume_name, type="volume", no_copy=True)],
            tmpfs={"/tmp": "rw,nosuid,nodev,noexec,size=16m,mode=0700,uid=10001,gid=10001"},
            environment={"HOME": "/tmp", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": ""},
            labels=labels,
            healthcheck={"Test": ["NONE"]}, log_config=LogConfig(type="none"),
            restart_policy={"Name": "no"}, detach=True,
        )
        container.start()
        container.reload()
        config, host = container.attrs["Config"], container.attrs["HostConfig"]
        mounts = container.attrs["Mounts"]
        if (len(mounts) != 1 or mounts[0]["Type"] != "volume" or mounts[0]["Name"] != volume_name
                or mounts[0]["Destination"] != "/workspace" or config["User"] != "10001:10001"
                or not host["ReadonlyRootfs"] or host["Privileged"]
                or host["NetworkMode"] != "none" or host["CapDrop"] != ["ALL"]
                or host["Memory"] != profile.memory_mb * 1024 * 1024
                or host["MemorySwap"] != profile.memory_mb * 1024 * 1024
                or host["PidsLimit"] != profile.pids or host["NanoCpus"] != profile.cpu_millis * 1_000_000):
            raise UnsafeExecution("container_control_mismatch")
        return container

    def populate(self, container, tree, writable):
        check_tree(tree)
        if not all(safe_path(path) for path in writable):
            raise UnsafeExecution("unsafe_write_scope")
        directories = set()
        for name in list(tree) + [p.rstrip("/") for p in writable]:
            parts = name.split("/")
            for i in range(1, len(parts)):
                directories.add("/".join(parts[:i]))
        directories.update(p.rstrip("/") for p in writable if p.endswith("/"))
        raw = io.BytesIO()
        staged = dict(tree)
        for name in writable:
            if not name.endswith("/"):
                staged.setdefault(name, b"")
        check_tree(staged)
        with tarfile.open(fileobj=raw, mode="w") as archive:
            for name in sorted(directories, key=lambda n: (n.count("/"), n)):
                entry = tarfile.TarInfo(name)
                entry.type = tarfile.DIRTYPE
                allowed = any(contains(path, name + "/") for path in writable)
                entry.uid = entry.gid = 10001 if allowed else 0
                entry.mode = 0o700 if allowed else 0o555
                archive.addfile(entry)
            for name, data in sorted(staged.items()):
                entry = tarfile.TarInfo(name)
                allowed = any(contains(path, name) for path in writable)
                entry.uid = entry.gid = 10001 if allowed else 0
                entry.mode, entry.size = (0o600 if allowed else 0o444), len(data)
                archive.addfile(entry, io.BytesIO(data))
        if not container.put_archive("/workspace", raw.getvalue()):
            raise UnsafeExecution("snapshot_copy_failed")

    def execute(self, container, command, profile, guard):
        if not guard():
            return {"status": "authority_lost", "exit_code": None, "output": b""}
        execution = self.client.api.exec_create(container.id, command, stdout=True, stderr=True,
                                                 user="10001:10001", workdir="/workspace")
        output = bytearray()
        overflow, done = threading.Event(), threading.Event()
        errors = []

        def collect():
            stream = None
            try:
                stream = self.client.api.exec_start(execution["Id"], stream=True, demux=True)
                for first, second in stream:
                    for part in (first, second):
                        if part:
                            room = profile.output_bytes - len(output)
                            output.extend(part[:room])
                            if len(part) > room:
                                overflow.set()
                                return
            except Exception as error:
                errors.append(type(error).__name__)
            finally:
                if stream is not None:
                    # docker-py 7.x returns CancellableStream, whose close()
                    # shuts down the socket but does not close its HTTP response.
                    # The streaming caller owns both, including normal EOF.
                    try:
                        try:
                            stream.close()
                        except OSError:
                            pass
                        finally:
                            stream._response.close()
                    except Exception as error:
                        errors.append(type(error).__name__)
                done.set()

        thread = threading.Thread(target=collect, daemon=True)
        thread.start()
        start, reason = time.monotonic(), None
        while True:
            if not guard():
                reason = "authority_lost"
            elif overflow.is_set():
                reason = "output_limit"
            elif time.monotonic() - start > profile.timeout_seconds:
                reason = "timed_out"
            if reason:
                self.stop(container.name, container.labels["awh.m2a.execution"], container.labels["awh.m2a.manifest"])
                break
            if done.is_set():
                break
            time.sleep(0.1)
        thread.join(timeout=4)
        if thread.is_alive():
            raise UnsafeExecution("output_reader_not_stopped")
        if reason:
            return {"status": reason, "exit_code": None, "output": bytes(output)}
        details = self.client.api.exec_inspect(execution["Id"])
        if errors or details["Running"] or details["ExitCode"] is None:
            raise UnsafeExecution("execution_result_uncertain")
        container.pause()  # Freeze all descendants before exporting mutable tmpfs.
        container.reload()
        if not container.attrs["State"]["Paused"]:
            raise UnsafeExecution("container_freeze_failed")
        return {"status": "exited", "exit_code": details["ExitCode"], "output": bytes(output)}

    def capture(self, container):
        chunks, _ = container.get_archive("/workspace")
        return from_archive(chunks)

    def stop(self, name, execution_id, manifest_hash):
        try:
            container = self.client.containers.get(name)
        except NotFound:
            return self._remove_volume(name, execution_id, manifest_hash)
        labels = container.labels
        if (labels.get("awh.m2a.execution") != execution_id
                or labels.get("awh.m2a.manifest") != manifest_hash):
            raise UnsafeExecution("container_identity_mismatch")
        container.reload()
        if container.attrs["State"].get("Paused"):
            container.unpause()
        container.reload()
        if container.attrs["State"]["Running"]:
            container.kill()
        container.wait(timeout=3)
        container.reload()
        if container.attrs["State"]["Running"] or container.attrs["State"].get("Paused"):
            return False
        container.remove()
        return self._remove_volume(name, execution_id, manifest_hash)

    def _remove_volume(self, name, execution_id, manifest_hash):
        try:
            volume = self.client.volumes.get(name + "-memory")
        except NotFound:
            return True
        labels = volume.attrs.get("Labels") or {}
        if (labels.get("awh.m2a.execution") != execution_id
                or labels.get("awh.m2a.manifest") != manifest_hash):
            raise UnsafeExecution("volume_identity_mismatch")
        volume.remove()
        return True
