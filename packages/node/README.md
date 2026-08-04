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

A walkthrough of the first working prototype is available on YouTube:
[Public Intelligence v1 Demo](https://www.youtube.com/watch?v=cGDWpOArB5I)

This video demonstrates the end-to-end integration of the Website, Scheduler, Node (showing the current v1 implementation), registration, heartbeats, and local inference.

A local end-to-end text demonstration is also available in [examples/demo.md](examples/demo.md).

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