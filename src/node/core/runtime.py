"""Runtime isolation and workspace management module."""

import asyncio
import logging
import os
import shutil
import subprocess
import tempfile

logger = logging.getLogger(__name__)


class WorktreeManager:
    """Manages isolated git worktrees for secure runtime workspace isolation."""

    def __init__(self, repo_path: str | None = None) -> None:
        """Initialize the WorktreeManager.

        Args:
            repo_path: Path to the base git repository. If not provided,
                searches upwards from this file for a .git directory.
        """
        if repo_path is None:
            # Search upwards for a .git directory
            curr = os.path.abspath(os.path.dirname(__file__))
            while curr != os.path.dirname(curr):
                if os.path.exists(os.path.join(curr, ".git")):
                    repo_path = curr
                    break
                curr = os.path.dirname(curr)
            if repo_path is None:
                repo_path = os.getcwd()

        self.repo_path = os.path.abspath(repo_path)
        self._worktrees: dict[str, str] = {}

    async def create_worktree(self, branch_name: str) -> str:
        """Create a new git worktree checked out to the specified branch.

        Confines all repository modifications and file editing sequences
        to the generated isolated git worktree directory.

        Args:
            branch_name: Name of the git branch to check out.

        Returns:
            The absolute string path to the isolated worktree directory.

        Raises:
            RuntimeError: If any of the git shell execution commands fail.
        """
        safe_name = "".join(c for c in branch_name if c.isalnum() or c in "-_")
        temp_dir = tempfile.gettempdir()
        worktree_path = os.path.abspath(
            os.path.join(temp_dir, f"node_worktree_{safe_name}")
        )

        # Cleanup existing directory path to prevent conflicts
        if os.path.exists(worktree_path):
            await self.cleanup_worktree(branch_name)

        # Check if the branch exists locally
        proc_check = await asyncio.create_subprocess_exec(
            "git",
            "show-ref",
            "--verify",
            f"refs/heads/{branch_name}",
            cwd=self.repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc_check.communicate()

        if proc_check.returncode != 0:
            # Branch doesn't exist, create it dynamically
            cmd = ["git", "worktree", "add", "-b", branch_name, worktree_path]
        else:
            # Branch exists, check it out directly
            cmd = ["git", "worktree", "add", worktree_path, branch_name]

        logger.info(
            "Creating worktree for branch %s at %s with cmd %s",
            branch_name,
            worktree_path,
            cmd,
        )

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=self.repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            err_msg = stderr.decode().strip()
            # If already exists in git worktree list but directory was deleted:
            if "already exists" in err_msg or "already registered" in err_msg:
                # Prune git worktree list and retry
                proc_prune = await asyncio.create_subprocess_exec(
                    "git",
                    "worktree",
                    "prune",
                    cwd=self.repo_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc_prune.communicate()

                # Retry the worktree add command
                proc_retry = await asyncio.create_subprocess_exec(
                    *cmd,
                    cwd=self.repo_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout_retry, stderr_retry = await proc_retry.communicate()
                if proc_retry.returncode != 0:
                    err_retry = stderr_retry.decode().strip()
                    raise RuntimeError(
                        f"Failed to create git worktree on retry: {err_retry}"
                    )
            else:
                raise RuntimeError(f"Failed to create git worktree: {err_msg}")

        self._worktrees[branch_name] = worktree_path
        return worktree_path

    async def cleanup_worktree(self, branch_name: str) -> None:
        """Remove the git worktree and clean up the filesystem directory.

        Args:
            branch_name: Name of the git branch associated with the worktree.
        """
        worktree_path = self._worktrees.get(branch_name)
        if not worktree_path:
            safe_name = "".join(c for c in branch_name if c.isalnum() or c in "-_")
            temp_dir = tempfile.gettempdir()
            worktree_path = os.path.abspath(
                os.path.join(temp_dir, f"node_worktree_{safe_name}")
            )

        logger.info("Cleaning worktree for branch %s at %s", branch_name, worktree_path)

        # Remove git worktree using force
        proc_remove = await asyncio.create_subprocess_exec(
            "git",
            "worktree",
            "remove",
            "-f",
            worktree_path,
            cwd=self.repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc_remove.communicate()

        # Prune any stale worktree metadata
        proc_prune = await asyncio.create_subprocess_exec(
            "git",
            "worktree",
            "prune",
            cwd=self.repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc_prune.communicate()

        # Ensure filesystem directory is fully removed
        if os.path.exists(worktree_path):
            try:
                shutil.rmtree(worktree_path)
            except Exception as e:
                logger.warning(
                    "Failed to delete worktree directory %s: %s",
                    worktree_path,
                    str(e),
                )

        self._worktrees.pop(branch_name, None)

    async def execute_in_sandbox(
        self,
        branch_name: str,
        command: list[str],
        image: str = "python:3.11-slim",
    ) -> subprocess.CompletedProcess[bytes]:
        """Execute a command in a sandboxed Docker container.

        Mounts the worktree of the specified branch as a read-write volume
        mapped to /workspace inside the container. Runs with constraints:
        non-root user (if host user is not root), 512MB memory limit,
        no host network, and a strict 60 seconds timeout.

        Args:
            branch_name: Name of the git branch associated with the worktree.
            command: Command list to execute in the sandbox.
            image: Docker image name to run.

        Returns:
            subprocess.CompletedProcess containing the execution results.

        Raises:
            ValueError: If no worktree is found for the branch.
            asyncio.TimeoutError: If execution exceeds 60 seconds.
        """
        worktree_path = self._worktrees.get(branch_name)
        if not worktree_path:
            raise ValueError(f"No active worktree found for branch: {branch_name}")

        docker_cmd = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{worktree_path}:/workspace",
            "-w",
            "/workspace",
            "--memory",
            "512m",
            "--network",
            "none",
        ]

        # Use non-root user matching host user's UID and GID where possible
        if hasattr(os, "getuid") and hasattr(os, "getgid"):
            uid = os.getuid()
            gid = os.getgid()
            if uid != 0:
                docker_cmd.extend(["--user", f"{uid}:{gid}"])

        docker_cmd.append(image)
        docker_cmd.extend(command)

        logger.info(
            "Executing sandboxed command on branch %s with cmd: %s",
            branch_name,
            docker_cmd,
        )

        proc = await asyncio.create_subprocess_exec(
            *docker_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60.0)
            returncode = proc.returncode if proc.returncode is not None else 0
        except asyncio.TimeoutError:
            logger.warning(
                "Sandboxed execution timed out on branch %s. Killing process...",
                branch_name,
            )
            try:
                proc.kill()
            except Exception as e:
                logger.error("Failed to kill sandboxed process: %s", str(e))
            stdout, stderr = await proc.communicate()
            raise asyncio.TimeoutError(
                "Sandbox execution exceeded timeout limit."
            ) from None

        return subprocess.CompletedProcess(
            args=docker_cmd,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )
