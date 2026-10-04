# Spanner Graph NL2GQL Agent (Demo)

> [!IMPORTANT]
> **Disclaimer:** This is **not** an officially supported Google product. This project is intended for **demonstration purposes only** and is **not intended for use in a production environment**. There is no official support or SLA provided for this repository—see [SUPPORT.md](SUPPORT.md) for details.

This repository is a **standalone, self-contained demonstration package** for the **Spanner Graph NL2GQL Conversational Agent** (`graph_agent/`) and its **FastAPI + SSE Web Interface** (`web/`).

It connects to an **already-deployed** Cloud Spanner `TransportGraph` database and can be run locally, in Google Cloud Shell, or deployed to Google Cloud Run completely on its own.

---

## Quickstart (Google Cloud Shell — 3 Commands)

```bash
# 1. Set your Google Cloud project
gcloud config set project YOUR_PROJECT_ID

# 2. Configure .env, install dependencies, and verify connection to Spanner & QueryData
./setup.sh

# 3. Launch the Web Interface on port 8080
./run.sh
```

Then click **Web Preview → Preview on port 8080** in the Cloud Shell toolbar.

---

## Deploying to Cloud Run

`./deploy.sh` builds and deploys the agent container to Google Cloud Run, automatically ensuring the `spanner-graph-agent-sa` runtime service account and its required IAM roles (`roles/spanner.databaseReader`, `roles/geminidataanalytics.queryDataUser`, `roles/aiplatform.user`, `roles/cloudaicompanion.user`) are configured:

```bash
# Deploy with Identity-Aware Proxy / authenticated access (default)
./deploy.sh

# Or deploy with unauthenticated access (if permitted by organization policy)
PUBLIC=true ./deploy.sh
```

To remove the Cloud Run service without touching the Cloud Spanner database:

```bash
./teardown.sh
```

---

## Run Modes (`./run.sh`)

| Command | Mode | Description |
| :--- | :--- | :--- |
| `./run.sh` *(or `./run.sh web`)* | **Custom Web UI (Default)** | Starts the FastAPI + SSE web console (`http://localhost:8080`) with interactive SVG topology map, GQL inspector, results table, CSV export, and sample prompts. |
| `./run.sh dev` | **ADK Developer UI** | Launches `adk web` with Cloud Shell CORS preconfigured. |
| `./run.sh cli` | **Terminal CLI** | Runs `adk run graph_agent` in the terminal. |

---

## Configuration (`.env`)

`./setup.sh` generates `.env` automatically if it does not already exist (or copy `.env.example` to `.env` before running `./setup.sh`):

| Variable | Default | Description |
| :--- | :--- | :--- |
| `GOOGLE_CLOUD_PROJECT` | *(Required)* | Active Google Cloud project ID for Vertex AI & QueryData. |
| `SPANNER_PROJECT_ID` | `$GOOGLE_CLOUD_PROJECT` | Project hosting the existing Cloud Spanner instance. |
| `SPANNER_LOCATION` | `europe-west1` | Cloud Spanner regional configuration. |
| `SPANNER_INSTANCE_ID` | `transport-graph-instance` | Existing Cloud Spanner instance ID. |
| `SPANNER_DATABASE_ID` | `transport-graph` | Existing Cloud Spanner database ID. |
| `SPANNER_GRAPH_IDS` | `TransportGraph` | Comma-separated Spanner Property Graph names. |
| `QUERY_DATA_LOCATION` | `us-central1` | Location for Gemini Data Analytics `QueryData` (`us-central1` or `global`). |
| `QUERY_DATA_EXECUTE_QUERY` | `true` | `true` = `QueryData` both generates and executes the query (default); `false` = `QueryData` generates the query and ADK Spanner tool executes it. |
| `NL2GQL_BACKEND` | `querydata` | `querydata` (default) or `gemini` (direct Gemini NL2GQL using `INFORMATION_SCHEMA.PROPERTY_GRAPHS`). |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Vertex AI Gemini model name. |
| `SHOW_SAMPLE_PROMPTS` | `true` | Controls whether the sample prompts sidebar and starter cards are visible by default when the Web UI loads (`true` or `false`). Users can also toggle visibility live in the top header. |
| `SAMPLE_PROMPTS_FILE` | `prompts.json` *(optional)* | Path to an optional JSON file with dataset-specific sample prompts for the Web UI. |

### Customizing Sample Prompts

An example sample prompts file is provided in [`sample_prompts.example.json`](sample_prompts.example.json). To use custom sample prompts for your dataset:

1. Copy the example file to `sample_prompts.json` (or `local_data/sample_prompts.json`, which is gitignored) and edit the categories and prompts:
   ```bash
   cp sample_prompts.example.json sample_prompts.json
   ```
   *(Alternatively, set `SAMPLE_PROMPTS_FILE=/path/to/your_prompts.json` in `.env`.)*
2. Each entry in the JSON array defines a `"category"` and a list of `"prompts"`:
   ```json
   [
     {
       "category": "Schema & Overview",
       "prompts": [
         "What node types and relationship types exist in the graph?",
         "Count the total number of nodes for each node label in the graph."
       ]
     }
   ]
   ```
3. To hide sample prompts by default when opening the Web UI, set `SHOW_SAMPLE_PROMPTS=false` in `.env` (you can still show or hide them at any time using the **Sample Prompts** toggle in the top header).

---

## Diagnostics & Testing

```bash
# Run preflight connectivity checks against Spanner, Gemini, and QueryData
uv run --frozen python scripts/doctor.py

# Run fast offline unit & FastAPI tests
uv run --frozen pytest

# Run end-to-end integration tests against the live Spanner database
RUN_INTEGRATION_TESTS=1 uv run --frozen pytest
```

See **[docs/architecture.md](docs/architecture.md)** and **[docs/tutorial.md](docs/tutorial.md)** for full details.

---

## Support & License

* **License:** Licensed under the [Apache License, Version 2.0](LICENSE).
* **Support:** This is **not** an officially supported Google product and is provided with **no support** (see [SUPPORT.md](SUPPORT.md)).
* **Demo Only:** This project is intended for demonstration purposes only. It is not intended for use in a production environment.
* **Vulnerability Rewards Program:** This project is not eligible for the [Google Open Source Software Vulnerability Rewards Program](https://bughunters.google.com/open-source-security). Eligibility for the [Google Open Source Software Vulnerability Rewards Program](https://bughunters.google.com/open-source-security) is determined by the [Google Open Source Software Vulnerability Reward Program Rules](https://bughunters.google.com/about/rules/open-source/google-open-source-software-vulnerability-reward-program-rules).


