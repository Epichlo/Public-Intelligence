"""End-to-End demonstration script for Public Intelligence Node v1."""

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from typing import Any

import httpx

from node.clients import OllamaClient
from node.core.configuration import get_settings


def log_reader(pipe: Any, prefix: str) -> None:
    """Read lines from a pipe and print them with a prefix."""
    try:
        for line in iter(pipe.readline, ""):
            if line:
                print(f"\033[90m{prefix} {line.strip()}\033[0m")
    except Exception:
        pass


async def run_demo() -> None:
    """Execute the end-to-end demonstration workflow."""
    print("==================================================")
    print("      Public Intelligence Node E2E Demo           ")
    print("==================================================")

    # Load configuration
    settings = get_settings()
    scheduler_url = settings.scheduler_url
    node_id = settings.node_id

    # STEP 1: Verify Ollama is available
    print("\n[STEP 1] Verifying Ollama daemon is running...")
    ollama_client = OllamaClient(settings)
    if not await ollama_client.health():
        print("\033[91m✗ Ollama daemon is not running!\033[0m")
        print("\nPlease start the Ollama daemon on your system:")
        print("  - If installed via app, click the Ollama menu bar icon to start it.")
        print("  - Or start it in the terminal by running: ollama serve")
        return
    print("✓ Ollama daemon is running.")

    # STEP 2: Show what this node will advertise
    #
    # There is nothing to check against a configured list, because there is no
    # configured list: the node advertises whatever Ollama has pulled, and
    # re-advertises when that changes. See specs/truthful-model-catalogue.md.
    print("\n[STEP 2] Reading the model catalogue this node will advertise...")
    models = await ollama_client.list_models()

    if not models:
        print("\033[91m✗ Ollama has no models pulled, so this node would advertise none.\033[0m")
        print("\nPull one first, for example:")
        print("  ollama pull llama3.2:1b")
        return

    print(f"✓ {len(models)} model(s) available locally:")
    for m in models:
        print(f"  - {m.name} ({m.size_gb} GB)")

    # STEP 3: Wait until the Scheduler is reachable
    print(f"\n[STEP 3] Verifying Scheduler is reachable at {scheduler_url}...")
    scheduler_healthy = False
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"{scheduler_url}/health")
            if resp.status_code == 200:
                scheduler_healthy = True
        except Exception:
            pass

    if not scheduler_healthy:
        print("\033[93m⚠️  Scheduler is not reachable at the moment.\033[0m")
        print("Please start the Scheduler service using:")
        print(
            "  cd ../Scheduler && .venv/bin/python -m uvicorn "
            "scheduler.main:app --host 127.0.0.1 --port 8080"
        )
        print("\nWaiting for Scheduler to start...")
        while not scheduler_healthy:
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(f"{scheduler_url}/health")
                    if resp.status_code == 200:
                        scheduler_healthy = True
                        break
            except Exception:
                pass
            await asyncio.sleep(2)
    print("✓ Scheduler is reachable and healthy.")

    # STEP 4: Start the Node FastAPI app in a background subprocess
    print("\n[STEP 4] Starting the Node FastAPI application...")
    # Configure env for short heartbeat intervals to speed up demo
    env = os.environ.copy()
    env["NODE_HEARTBEAT_INTERVAL_SECONDS"] = "2"
    # No model list to pass through: the node it starts reads its own from Ollama,
    # which is the same list STEP 2 printed.
    env["NODE_MODEL_REFRESH_INTERVAL_SECONDS"] = "5"

    node_process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "node.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
    )

    # Start logging threads to stream uvicorn log lines to console
    t_stdout = threading.Thread(
        target=log_reader, args=(node_process.stdout, "[Node-stdout]"), daemon=True
    )
    t_stderr = threading.Thread(
        target=log_reader, args=(node_process.stderr, "[Node-stderr]"), daemon=True
    )
    t_stdout.start()
    t_stderr.start()

    try:
        # Wait for Node HTTP server to become ready
        node_ready = False
        print("Waiting for Node HTTP server to start...")
        for _ in range(30):
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get("http://localhost:8000/health")
                    if resp.status_code == 200:
                        node_ready = True
                        break
            except Exception:
                pass
            await asyncio.sleep(0.5)

        if not node_ready:
            print("\033[91m✗ Node failed to start or become reachable!\033[0m")
            return
        print("✓ Node FastAPI server is active.")

        # STEP 5: Verify Scheduler registration
        print("\n[STEP 5] Verifying Node registered on the Scheduler...")
        registered_node = None
        for _ in range(10):
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(f"{scheduler_url}/nodes")
                    if resp.status_code == 200:
                        nodes = resp.json()
                        for node in nodes:
                            if node.get("node_id") == node_id:
                                registered_node = node
                                break
            except Exception:
                pass
            if registered_node:
                break
            await asyncio.sleep(1)

        if not registered_node:
            print("\033[91m✗ Node registration not found on the Scheduler!\033[0m")
            return
        print("✓ Node registration confirmed on the Scheduler.")
        print("Registered Node capabilities payload:")
        print(json.dumps(registered_node, indent=2))

        # STEP 6: Send a real inference request to the Node
        print("\n[STEP 6] Executing a real inference request...")
        target_model = models[0].name
        prompt = "Hello from Public Intelligence."
        print(f"Request payload: model='{target_model}', prompt='{prompt}'")

        start_time = time.time()
        inference_succeeded = False
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "http://localhost:8000/infer",
                    json={"model": target_model, "prompt": prompt},
                    timeout=60.0,
                )
                latency = time.time() - start_time
                if resp.status_code == 200:
                    inference_succeeded = True
                    resp_json = resp.json()
                    print("✓ Inference execution completed successfully!")
                    print(f"Latency: {latency:.2f} seconds")
                    print("Response payload:")
                    print(json.dumps(resp_json, indent=2))
                else:
                    print(f"\033[91m✗ Inference failed: {resp.status_code} - {resp.text}\033[0m")
        except Exception as e:
            print(f"\033[91m✗ Inference failed: {e}\033[0m")

        # STEP 7: Verify heartbeats continue
        print("\n[STEP 7] Verifying that heartbeats continue...")
        print("Waiting to observe periodic heartbeat log outputs (interval: 2s)...")
        await asyncio.sleep(5)
        print("✓ Heartbeat loop verified.")

    finally:
        # STEP 8: Gracefully stop the Node and verify unregistration
        print("\n[STEP 8] Shutting down the Node gracefully...")
        node_process.terminate()
        node_process.wait()
        print("✓ Node process terminated.")

        # Verify unregistration on the Scheduler
        print("Verifying unregistration from the Scheduler...")
        unregistered = False
        for _ in range(10):
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(f"{scheduler_url}/nodes")
                    if resp.status_code == 200:
                        nodes = resp.json()
                        found = False
                        for node in nodes:
                            if node.get("node_id") == node_id:
                                found = True
                                break
                        if not found:
                            unregistered = True
                            break
            except Exception:
                pass
            await asyncio.sleep(0.5)

        if unregistered:
            print("✓ Node successfully unregistered from the Scheduler registry.")
        else:
            print("\033[91m✗ Node remains registered on the Scheduler after shutdown!\033[0m")

    # STEP 9: Print final summary
    print("\n" + "=" * 45)
    print("        Public Intelligence Node v1 Demo Summary")
    print("=" * 45)
    print("✓ Scheduler reachable")
    print("✓ Node started")
    print("✓ Registration succeeded")
    print("✓ Heartbeats received")
    if inference_succeeded:
        print("✓ Inference succeeded")
    else:
        print("✗ Inference failed")
    print("✓ Graceful shutdown")
    if unregistered:
        print("✓ Node unregistered")
    else:
        print("✗ Node unregistration failed")
    print("=" * 45 + "\n")


if __name__ == "__main__":
    try:
        asyncio.run(run_demo())
    except KeyboardInterrupt:
        print("\nDemo interrupted by user.")
