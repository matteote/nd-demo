# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

FROM python:3.13-slim

# Install uv from the official Astral image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies in a cached layer using the public PyPI lockfile
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy application source and static web assets
COPY graph_agent/ ./graph_agent/
COPY web/ ./web/

ENV PYTHONUNBUFFERED=1 \
    PORT=8080 \
    GOOGLE_CLOUD_SPANNER_MULTIPLEXED_SESSIONS=false \
    SPANNER_DISABLE_BUILTIN_METRICS=true

EXPOSE 8080

CMD ["uv", "run", "--frozen", "--no-dev", "uvicorn", "web.server:app", "--host", "0.0.0.0", "--port", "8080"]
