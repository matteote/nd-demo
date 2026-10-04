# Step-by-Step Cloud Shell Tutorial

This tutorial walks you through configuring and running the **Spanner Graph NL2GQL Agent** in **Google Cloud Shell** against an already-deployed `TransportGraph` Cloud Spanner database, exploring the property graph in the Web UI, and optionally deploying a shareable endpoint on Cloud Run.

---

## Step 1: Open Google Cloud Shell

1. Open the [Google Cloud Console](https://console.cloud.google.com/).
2. Select your Google Cloud project.
3. Click the **Activate Cloud Shell** icon (`>_`) in the top-right navigation bar.

---

## Step 2: Configure the Agent

Run the following commands in your Cloud Shell terminal from the repository root:

```bash

# Ensure your active project is set
gcloud config set project YOUR_PROJECT_ID

# Configure .env, install Python dependencies, and run preflight checks
./setup.sh
```

> **Custom Spanner Instance / Database:** If your Spanner instance or database uses custom names, pass them when running `setup.sh`:
> ```bash
> SPANNER_INSTANCE_ID=my-instance SPANNER_DATABASE_ID=my-db ./setup.sh
> ```

---

## Step 3: Launch the Web Interface in Cloud Shell

Start the web server:

```bash
./run.sh
```

In the Cloud Shell toolbar:
1. Click the **Web Preview** button (top right of the terminal pane).
2. Select **Preview on port 8080**.

A new browser tab will open displaying the **TransportGraph Console** web interface.

---

## Step 4: Explore the Graph in Natural Language

### 1. Schema & Node Discovery
Click the first sample prompt in the left sidebar:
> *"What node types and relationship types exist in the graph?"*

**What to observe:**
- Watch the tool status pill (`query_graph_data`) complete in real time.
- Inspect the **Generated query** block (and use **Copy query** if needed) to see the GQL/SQL query produced for your Spanner Property Graph.
- View the **Spanner Graph Query Results** table and click **Export CSV** to download results.

### 2. Connectivity & Path Traversal
Ask a multi-hop connectivity question or click one of the connectivity prompts in the sidebar:
> *"Show a sample of connected node pairs and the edges between them."*

### 3. Loading & Toggling Custom Sample Prompts (Optional)
- Use [`sample_prompts.example.json`](../sample_prompts.example.json) as a template to create your own dataset-specific prompts:
  ```bash
  cp sample_prompts.example.json sample_prompts.json
  ```
  *(Or place it in `local_data/sample_prompts.json` or set `SAMPLE_PROMPTS_FILE=/path/to/prompts.json` in `.env`.)*
- Refresh the browser to see your custom prompt categories in the left sidebar and welcome screen.
- You can show or hide the sample prompts at any time using the **Sample Prompts** toggle in the top header, or set `SHOW_SAMPLE_PROMPTS=false` in `.env` to hide them by default.

---

## Step 5: (Optional) Deploy to Cloud Run

To host the web interface on Google Cloud Run:

```bash
./deploy.sh
```
