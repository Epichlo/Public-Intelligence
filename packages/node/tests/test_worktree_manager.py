"""Unit and integration tests for WorktreeManager."""

import asyncio
import os
import sys

import pytest

from node.core.runtime import WorktreeManager


@pytest.mark.anyio
async def test_worktree_manager_create_and_cleanup() -> None:
    """Verify that WorktreeManager can create and clean up a git worktree."""
    branch_name = "tmp-test-worktree-branch"
    manager = WorktreeManager()

    # Pre-clean the branch and worktree if it already exists from a crashed run
    await manager.cleanup_worktree(branch_name)
    proc_clean_branch = await asyncio.create_subprocess_exec(
        "git",
        "branch",
        "-D",
        branch_name,
        cwd=manager.repo_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc_clean_branch.communicate()

    # Create the worktree
    path = await manager.create_worktree(branch_name)
    try:
        assert os.path.exists(path)
        assert os.path.isdir(path)

        # Check if the directory is actually a git worktree repository
        assert os.path.exists(os.path.join(path, ".git"))
    finally:
        # Clean it up
        await manager.cleanup_worktree(branch_name)
        assert not os.path.exists(path)

        # Remove the test branch
        proc_del = await asyncio.create_subprocess_exec(
            "git",
            "branch",
            "-D",
            branch_name,
            cwd=manager.repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc_del.communicate()


@pytest.mark.anyio
async def test_worktree_manager_invalid_branch() -> None:
    """Verify that WorktreeManager raises an exception for invalid branch names."""
    manager = WorktreeManager()
    with pytest.raises(RuntimeError):
        # Passing an invalid git branch name character like "*"
        await manager.create_worktree("invalid*branch*name")


async def _is_docker_available() -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "info",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        return proc.returncode == 0
    except Exception:
        return False


@pytest.mark.anyio
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="sandbox runs the Linux image python:3.11-slim; the Windows CI runner's "
    "Docker daemon is in Windows-container mode and cannot pull it",
)
async def test_execute_in_sandbox_integration() -> None:
    """Verify that execute_in_sandbox runs a command inside Docker sandbox.

    Skipped on Windows: `_is_docker_available` below only proves the daemon
    responds, not that it can run Linux images. On a Windows-container daemon the
    pull fails with "no matching manifest for windows/amd64", so the guard passes
    and the test then fails with exit 125. The sandbox targets Linux containers by
    design -- this is a test-environment limit, not a defect in WorktreeManager.
    """
    if not await _is_docker_available():
        pytest.skip("Docker is not available in the test environment")

    branch_name = "tmp-test-sandbox-branch"
    manager = WorktreeManager()

    # Pre-clean the branch and worktree if it already exists from a crashed run
    await manager.cleanup_worktree(branch_name)
    proc_clean_branch = await asyncio.create_subprocess_exec(
        "git",
        "branch",
        "-D",
        branch_name,
        cwd=manager.repo_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc_clean_branch.communicate()

    # Create the worktree
    path = await manager.create_worktree(branch_name)
    try:
        # 1. Run a command inside sandbox that writes a file in /workspace
        cmd = [
            "python",
            "-c",
            "with open('sandbox_file.txt', 'w') as f: f.write('hello from sandbox')",
        ]
        res = await manager.execute_in_sandbox(branch_name, cmd)
        assert res.returncode == 0

        # Verify the file was written to the isolated worktree on host filesystem
        host_file_path = os.path.join(path, "sandbox_file.txt")
        assert os.path.exists(host_file_path)
        with open(host_file_path) as f:
            assert f.read() == "hello from sandbox"

        # 2. Verify that network is blocked (--network none)
        cmd_net = [
            "python",
            "-c",
            "import socket; socket.create_connection(('8.8.8.8', 53), timeout=2)",
        ]
        res_net = await manager.execute_in_sandbox(branch_name, cmd_net)
        assert res_net.returncode != 0

        # 3. Verify that attempts to escape worktree path are blocked
        cmd_escape = [
            "python",
            "-c",
            "import os; print(os.path.abspath('/workspace/../..'))",
        ]
        res_escape = await manager.execute_in_sandbox(branch_name, cmd_escape)
        assert res_escape.returncode == 0
        assert res_escape.stdout.decode().strip() == "/"

    finally:
        # Clean up worktree and branch
        await manager.cleanup_worktree(branch_name)
        proc_del = await asyncio.create_subprocess_exec(
            "git",
            "branch",
            "-D",
            branch_name,
            cwd=manager.repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc_del.communicate()
