# IT Support Ticket Management System

A comprehensive **AI-powered IT Support Ticket Management System** built with an autonomous **Agentic AI workflow** for end‑to‑end ticket lifecycle automation.

## 📌 System Workflow

Below is the complete workflow diagram illustrating ticket creation, processing, user engagement, and continuous improvement:

![Workflow](workflow.png)

---

## 🚀 Features

* **Automated Email Ticketing** – IMAP integration for automatic ticket creation from inbound emails.
* **AI-Powered Classification** – Supports both closed‑source and open‑source LLMs for ticket categorization.
* **Smart Assignment Engine** – Skill‑based and workload‑balanced technician assignment.
* **AI Resolution Generation** – Generates recommended resolutions using historical ticket data.
* **Automated Notifications** – Sends confirmation, escalation, and resolution emails.
* **Knowledge Management** – Persistent knowledge base with similar ticket detection.
* **Backend‑Driven** – Entire workflow operates independently of UI layers.
* **FastAPI Backend** – Clean, modular REST API for all operations.
* **Swagger/OpenAPI Docs** – Interactive interface for testing APIs.

---

## 📁 Project Structure

```
teamlogic-autotask/
├── README.md
├── requirements.txt
├── .env
├── app.py
├── config.py
├── start_backend.py
│
├── backend/
│   ├── main.py
│   ├── run.py
│   ├── test_api.py
│   ├── requirements.txt
│   ├── README.md
│   └── API_ENDPOINTS.md
│
├── src/
│   ├── agents/
│   │   ├── intake_agent.py
│   │   ├── assignment_agent.py
│   │   └── notification_agent.py
│   │
│   ├── processors/
│   │   ├── ai_processor.py
│   │   ├── ticket_processor.py
│   │   └── image_processor.py
│   │
│   ├── database/
│   │   └── snowflake_db.py
│   │
│   ├── data/
│   │   └── data_manager.py
│   │
│   └── ui/
│       └── components.py
│
├── data/
│   ├── reference_data.txt
│   ├── knowledgebase.json
│   └── ticket_sequence.json
│
├── logs/
└── docs/
```

---

## 📚 Documentation

* Full backend API documentation: `backend/API_ENDPOINTS.md`
* Detailed backend usage: `backend/README.md`
* System configuration: `config.py`

---

## ▶️ Running the System

### **Backend (FastAPI)**

```
python start_backend.py
```

Swagger UI will be available at:

```
http://localhost:8000/docs
```

### **Frontend (Streamlit)**

```
streamlit run app.py
```

---

## 🧠 Knowledge Base & Learning

* Active learning loop updates `knowledgebase.json`.
* Similar ticket detection improves accuracy over time.

---

## 🔒 Environment Variables

Your `.env` file should include:

```
IMAP_HOST=
IMAP_USER=
IMAP_PASSWORD=
SNOWFLAKE_USER=
SNOWFLAKE_PASSWORD=
SNOWFLAKE_ACCOUNT=
LLM_API_KEY=
```

---

## 📞 Support & Contributions

Contributions are welcome! Submit issues or pull requests to enhance the platform.
