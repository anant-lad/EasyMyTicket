# EasyMyTicket — Documentation Index

**Project:** AI-powered IT Support Ticketing Platform with AWS Infrastructure  
**Stack:** Python · FastAPI · LangGraph · Groq LLMs · PostgreSQL 16 · Redis · AWS EKS  
**Date:** June 2026

---

## Documents

| # | File | Contents |
|---|---|---|
| 1 | [01_AWS_INFRASTRUCTURE.md](01_AWS_INFRASTRUCTURE.md) | Full AWS architecture diagram, VPC topology, EKS config, IAM/IRSA, CI/CD, K8s resources |
| 2 | [02_BACKEND_MODULES.md](02_BACKEND_MODULES.md) | All Python modules explained — agents, LangGraph nodes, DB layer, routes, Redis, SQS |
| 3 | [03_FUNCTIONALITY_FLOWS.md](03_FUNCTIONALITY_FLOWS.md) | Feature-by-feature flows — ticket pipeline, agentic repair, semantic search, frontend, observability |
| 4 | [04_TECHNICAL_DETAILS.md](04_TECHNICAL_DETAILS.md) | LLM strategy, connection pooling, WebSocket architecture, security model, config reference |
| 5 | [05_COMPLETE_FLOW_DIAGRAM.md](05_COMPLETE_FLOW_DIAGRAM.md) | Master end-to-end diagrams — full system, ticket lifecycle, remediation loop, CI/CD |

---

## Quick Reference

### What happens when a ticket is submitted?
→ See [03_FUNCTIONALITY_FLOWS.md — Feature 1](03_FUNCTIONALITY_FLOWS.md)

### How does the desktop agent fix issues automatically?
→ See [03_FUNCTIONALITY_FLOWS.md — Feature 2](03_FUNCTIONALITY_FLOWS.md) and [05_COMPLETE_FLOW_DIAGRAM.md — Agentic Remediation](05_COMPLETE_FLOW_DIAGRAM.md)

### What AWS services are used and why?
→ See [01_AWS_INFRASTRUCTURE.md](01_AWS_INFRASTRUCTURE.md)

### What do the AI agents actually do?
→ See [02_BACKEND_MODULES.md — AI Agents](02_BACKEND_MODULES.md)

### How are LLMs used throughout the system?
→ See [04_TECHNICAL_DETAILS.md — LLM Architecture](04_TECHNICAL_DETAILS.md)

### How is the database structured?
→ See [03_FUNCTIONALITY_FLOWS.md — Database Schema](03_FUNCTIONALITY_FLOWS.md)

---

## Architecture in One Paragraph

EasyMyTicket is a cloud-native IT support ticketing platform running on AWS EKS in ap-south-1. When a user submits a ticket through the Next.js portal, a **6-node LangGraph pipeline** runs: it saves the ticket to RDS PostgreSQL, extracts metadata with a small LLM (Llama-3.1-8b), classifies it with a large LLM (Llama-3.3-70b) against a picklist, performs **semantic similarity search** across 73,000 historical tickets using sentence-transformers embeddings cached in ElastiCache Redis, decides whether a desktop agent can auto-fix it, either assigns a skilled technician or launches an **agentic multi-turn repair loop** on the user's machine via WebSocket, generates a resolution guide, and sends email notifications through SQS. The desktop agent (Python, cross-platform) runs commands from a sandboxed registry — read-only diagnostics freely, write/fix operations only after technician approval. All infrastructure is defined in Terraform and deployed to EKS via GitHub Actions CI/CD.
