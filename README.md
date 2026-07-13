# Public Intelligence Node

A Public Intelligence Node is a compute worker that joins the network, advertises available models, executes inference locally using Ollama, and communicates with the Scheduler.

Version 1 establishes the complete lifecycle of a compute node.

---

## Current Features

- Scheduler registration
- Heartbeats
- Ollama integration
- Local inference API
- Runtime lifecycle management
- Graceful shutdown
- End-to-end demonstration
- Comprehensive test suite

---

## Architecture

```text
            Scheduler

               ▲

 Registration / Heartbeats

               │

               ▼

        Public Intelligence Node

               │

               ▼

          Ollama Client

               │

               ▼

             Ollama
```

---

## Running

Start Ollama

```bash
ollama serve
```

Run the Node

```bash
python -m node.main
```

---

## Demo

A complete end-to-end demonstration is available in

```
examples/demo.md
```

---

## Version

Current Release

```
v1.0.0
```

---

## Future Work

Version 2 will introduce:

- Automatic hardware discovery
- Better runtime metrics
- Improved monitoring
- Enhanced node capabilities

---

## Related Repositories

- Public Intelligence Scheduler
- Public Intelligence Website

---

## License

Apache 2.0