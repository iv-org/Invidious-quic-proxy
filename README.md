# [WIP] Quic proxy built in Python for the Invidious project.

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
host = "0.0.0.0"
port = 7192
```
