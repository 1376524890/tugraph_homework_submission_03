import kagglehub

# Download latest version
path = kagglehub.dataset_download("jsrojas/ip-network-traffic-flows-labeled-with-87-apps")

print("Path to dataset files:", path)