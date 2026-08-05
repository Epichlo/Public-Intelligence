# Public Intelligence Node v1 End-to-End Demonstration

This guide describes how to run the end-to-end demonstration proving that the Scheduler and Node repositories interoperate correctly under local conditions.

## Prerequisites

Before running the demonstration, ensure you have:

1. **Python 3.10+** installed.
2. **Ollama** running locally on your system.
3. The **Scheduler** repository cloned adjacent to this `Node` repository (i.e. both repositories are siblings in the same parent directory).

## Setup Instructions

### 1. Start Ollama and Pull the Model
Ensure that Ollama is running and download a lightweight model for the demonstration:
```bash
ollama pull llama3.2:1b
```

### 2. Configure the Node Dotenv File
Copy the example environment file:
```bash
cp .env.example .env
```
There is no model list to set. The node advertises whatever Ollama has pulled, so
pull the model you want to serve instead:
```bash
ollama pull llama3.2:1b
```

### 3. Install Dependencies & Build Node virtualenv
Create and prepare the Node environment:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 4. Build Scheduler virtualenv
In a separate terminal shell, navigate to the Scheduler directory and install its dependencies:
```bash
cd ../Scheduler
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Running the Demonstration

1. In your Node virtualenv terminal shell, start the E2E demonstration script:
```bash
python examples/demo.py
```

2. If the Scheduler is not running, the script will show a warning and wait. In your Scheduler virtualenv terminal, start the Scheduler:
```bash
python -m uvicorn scheduler.main:app --host 127.0.0.1 --port 8080
```

3. Watch the Node console. The script will automatically:
   - Check Ollama availability and model presence.
   - Wait for the Scheduler to become reachable.
   - Start the Node as a background subprocess.
   - Verify Node registration on the Scheduler and display the registered capabilities.
   - Dispatch a real HTTP `POST /infer` inference request to the Node and print the output and latency.
   - Verify periodic heartbeats are received by the Scheduler.
   - Shut down the Node process gracefully and confirm the Scheduler unregisters the node cleanly.

## Expected Summary Output

When the script successfully finishes, it will print a final summary:

```text
=============================================
   Public Intelligence Node v1 Demo Summary
=============================================
✓ Scheduler reachable
✓ Node started
✓ Registration succeeded
✓ Heartbeats received
✓ Inference succeeded
✓ Graceful shutdown
✓ Node unregistered
=============================================
```
