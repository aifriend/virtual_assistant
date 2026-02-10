# Virtual Assistant

Chatbot platform with a modular microservices architecture, connectable to Skype for Business. Built with Rasa Core, IBM Watson, and custom NLP components using TensorFlow embeddings.

## Architecture

The system follows a CONVERSE component pattern with independent, Docker-containerized services:

```
┌─────────────────────────────────────────────┐
│                  Interface                   │
├──────────┬──────────┬──────────┬────────────┤
│ Security │ Context  │ Dialog   │ Confidence │
│ Manager  │ Manager  │ Manager  │ Controller │
├──────────┴──────────┴──────────┴────────────┤
│            Configuration Service             │
├──────────┬──────────┬──────────┬────────────┤
│  Rasa    │  Watson  │   SAP    │    RPA     │
│  Core    │ Assistant│ Connector│  Service   │
├──────────┴──────────┴──────────┴────────────┤
│         MongoDB (Tracker Store)              │
└─────────────────────────────────────────────┘
```

## Project Structure

```
├── core/                  # Core platform services
│   ├── business/          # Business logic engine
│   ├── confidence/        # Response confidence scoring
│   ├── configuration/     # Centralized config service
│   ├── context/           # Conversation context manager
│   ├── dialog/            # Dialog flow manager
│   ├── memory/            # Memory/state manager
│   ├── response/          # Response generation
│   └── security/          # Auth and security
├── enterprise/            # Enterprise integrations
│   ├── rasa/              # Rasa Core + NLU
│   ├── watson/            # IBM Watson Assistant
│   ├── sap/               # SAP connector
│   └── rpa/               # Robotic Process Automation
├── interface/             # Frontend interface
└── deploy/                # Docker deployment configs
```

## Tech Stack

- **Language:** Python 3.6+
- **NLP:** Rasa Core, TensorFlow
- **Enterprise:** IBM Watson, SAP
- **Database:** MongoDB
- **Deployment:** Docker, Docker Compose
- **Interface:** Skype for Business

## Prerequisites

- Docker & Docker Compose
- Python 3.6+

## Quick Start

1. Clone the repository:
   ```bash
   git clone https://github.com/aifriend/virtual_assistant.git
   cd virtual_assistant
   ```

2. Copy the environment file and set your credentials:
   ```bash
   cp .env.example .env
   # Edit .env with your actual credentials
   ```

3. Build and run:
   ```bash
   docker-compose -f 0-docker-compose.yml build
   docker-compose -f 0-docker-compose.yml up -d
   ```

4. Train the Rasa model:
   ```bash
   make clean-model
   docker exec -it rasa_core bash -c "python -m rasa_core.train ..."
   ```

## Configuration

All services share a centralized configuration through the `configuration_service`. Copy `config.py` to all modules:

```bash
make copy-config
```

## Useful Commands

```bash
make clean-upload    # Clean project for production
make clean-logs      # Remove all log files
make clean-model     # Remove trained models
make clean-mongo     # Reset MongoDB data
make show-process    # Show active network ports
```

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

## Author

**Jose** — [@aifriend](https://github.com/aifriend)
