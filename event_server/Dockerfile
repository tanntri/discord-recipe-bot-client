# Stage 1: Build Stage
FROM python:3.12-slim AS builder

# Install uv
RUN pip install uv

# Set the working directory and copy dependencies
WORKDIR /app
COPY requirements.txt .

# Use uv to install dependencies into a virtual environment
RUN uv venv && uv pip install -r requirements.txt

# Stage 2: Final Stage
FROM python:3.12-slim

# Set the working directory
WORKDIR /app

# Copy only the installed virtual environment from the builder stage
COPY --from=builder /app/.venv /app/.venv

# Set the PATH to include the virtual environment's binaries
ENV PATH="/app/.venv/bin:$PATH"

# Copy the rest of the application code
COPY . .

# Run the bot
CMD ["python", "main.py"]