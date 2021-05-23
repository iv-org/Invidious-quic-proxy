# Quic proxy built in Python for the Invidious project.

## Installation
1. Clone the repository
2. Create a python virtual environment
3. Install dependencies through pip `pip install -r requirements.txt`

## Usage

All requests is done through POST. A data content of 
<br>
```sh
{"headers": {"Content-Type": "application/json"},
"url": "https://www.youtube.com/youtubei/v1/browse?key=AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8", 
"method": "POST", "data": {"context": {...}}
```
Will use HTTP/3 to query the specified URL with the specified data, method and headers.

## Configuration
The port and address can be changed in config.toml, located in the default OS config location.

```toml
# Host address to bind to
host = "0.0.0.0"
# Port to listen on
port = 7192
# Amount of workers to process quic requests
open_connections = 5
```
