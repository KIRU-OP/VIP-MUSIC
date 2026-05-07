# Python 3.13 aur Node.js ke latest stable version ka use
FROM nikolaik/python-nodejs:python3.13-nodejs22

# System dependencies install karna
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg aria2 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# App directory setup
COPY . /app/
WORKDIR /app/

# Pip ko upgrade karna aur dependencies install karna
RUN python -m pip install --no-cache-dir --upgrade pip

# Agar aapne pyproject.toml banaya hai, toh ye command use karein:
RUN pip install --no-cache-dir .

# Agar aapke paas requirements.txt abhi bhi hai, toh ise use kar sakte hain:
# RUN pip3 install --no-cache-dir --upgrade --requirement requirements.txt

# Bot start karne ki command
CMD python3 -m VIPMUSIC
