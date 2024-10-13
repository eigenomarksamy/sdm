import tkinter as tk
from tkinter import filedialog, messagebox

from cfg_mngr import Cfg
from run import execute

# Placeholder for your download function
def download_music():
    url = url_entry.get()
    destination = destination_entry.get()

    cfgObj = Cfg(directory=destination)

    if url and destination:
        try:
            execute(cfgObj, [url])
            messagebox.showinfo("Success", f"Music downloaded from {url} to {destination}")
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {e}")
    else:
        messagebox.showwarning("Input error", "Please enter both URL and destination folder")

# Function to browse destination folder
def browse_destination():
    folder_selected = filedialog.askdirectory()
    if folder_selected:
        destination_entry.delete(0, tk.END)  # Clear existing text in the entry
        destination_entry.insert(0, folder_selected)  # Insert selected folder

# Create main window
root = tk.Tk()
root.title("Music Downloader")

# URL Entry
url_label = tk.Label(root, text="Music URL:")
url_label.pack(pady=5)

url_entry = tk.Entry(root, width=50)
url_entry.pack(pady=5)

# Destination Entry
destination_label = tk.Label(root, text="Destination Folder:")
destination_label.pack(pady=5)

destination_entry = tk.Entry(root, width=50)
destination_entry.pack(pady=5)

# Browse Button
browse_button = tk.Button(root, text="Browse", command=browse_destination)
browse_button.pack(pady=5)

# Download Button
download_button = tk.Button(root, text="Download", command=download_music)
download_button.pack(pady=10)

# Start the GUI event loop
root.mainloop()
