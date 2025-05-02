FROM public.ecr.aws/lambda/python:3.11

WORKDIR /tmp

# Copy the lock file for dependency installation
COPY uv.lock .

# Install uv for dependency management
RUN pip install --no-cache-dir uv

COPY pyproject.toml README.md LICENSE ${LAMBDA_TASK_ROOT}/
# Install dependencies from lock file
RUN uv sync

# Create a directory for the project
WORKDIR ${LAMBDA_TASK_ROOT}

# Copy fraud_detection package and pyproject.toml
# Note: These files must be in the Docker build context
# Use a .dockerignore file to exclude unnecessary files
COPY fraud_detection/ ${LAMBDA_TASK_ROOT}/fraud_detection/


# Install our package
RUN pip install -e .

# Set the CMD to the handler function
CMD [ "fraud_detection.inference.lambda_handler.lambda_handler" ] 