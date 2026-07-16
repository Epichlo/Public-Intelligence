"""Unit and integration tests for WorktreeManager."""

import asyncio
import os

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
