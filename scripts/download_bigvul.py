"""Download the original BigVul zip (mirrored on Hugging Face) into data/raw/."""
from huggingface_hub import hf_hub_download

path = hf_hub_download(
    repo_id="starsofchance/MSR_data_cleaned",
    filename="MSR_data_cleaned.zip",
    repo_type="dataset",
    local_dir="data/raw",
    token=False,  # public dataset; skip reading the unreadable token file
)
print("Downloaded to:", path)