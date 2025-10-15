FROM python:3.11

ARG CLAUDE_CODE_VERSION=latest
ARG NODE_VERSION=20.11.0

WORKDIR /workspace

# Update and install dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    libssl-dev \
    libffi-dev \
    libxml2-dev \
    libxslt1-dev \
    zlib1g-dev \
    iputils-ping \
    less \
    git \
    procps \
    sudo \
    fzf \
    zsh \
    man-db \
    unzip \
    gnupg2 \
    gh \
    iptables \
    ipset \
    iproute2 \
    dnsutils \
    aggregate \
    jq \
    nano \
    vim \
    curl \
    npm \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set the default shell to zsh rather than sh
ENV SHELL=/bin/zsh

# Set the default editor and visual
ENV EDITOR=nano
ENV VISUAL=nano

# Install Node.js
ENV NODE_VERSION=${NODE_VERSION}
RUN npm install npm@latest -g && \
    npm install n -g && \
    n ${NODE_VERSION}

# Install Claude
RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}

# Upgrade pip and install Python packages
RUN pip install --upgrade pip

RUN pip install google-cloud-bigquery pyarrow db-dtypes pandas matplotlib scikit-learn seaborn numpy scipy statsmodels xgboost plotly tabulate snowflake-connector-python duckdb openpyxl
RUN pip install dbt-duckdb

# Install Claude Agent SDK
RUN pip install claude-agent-sdk

# Copy main run script
#COPY run_test_in_container.py /agent/run_test_in_container.py # Done from python code

# Set the default command to run when starting the container
CMD ["/bin/bash"]
#ENTRYPOINT [ "python3", "/workspace/agent/run_test_in_container.py" ]
