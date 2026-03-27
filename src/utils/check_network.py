import urllib.request
import urllib.error
import time
import socket

url = "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/0/0/0"

print(f"Testing connectivity to: {url}")
start_time = time.time()

try:
    # Set a timeout of 10 seconds for the test
    with urllib.request.urlopen(url, timeout=10) as response:
        print(f"Success! Status Code: {response.status}")
        print(f"Time taken: {time.time() - start_time:.2f} seconds")
except urllib.error.URLError as e:
    print(f"URLError: {e.reason}")
    if isinstance(e.reason, socket.timeout):
        print("Error type: Socket Timeout")
    elif isinstance(e.reason, OSError):
         print(f"Error type: OSError ({e.reason})")
except socket.timeout:
    print("Socket Timeout")
except Exception as e:
    print(f"An error occurred: {e}")

print(f"Total test time: {time.time() - start_time:.2f} seconds")
