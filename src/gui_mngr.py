import time
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter.ttk import Progressbar
from src.cfg_mngr import Cfg
from src.osd_mngr import run_gui

class DownloaderGUI:

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("eigenSDM")
        self.create_widgets()

    def create_widgets(self):
        self.url_label = tk.Label(self.root, text="Spotify Playlist URL:")
        self.url_label.pack(padx=5, pady=5)
        
        self.url_entry = tk.Entry(self.root, width=50)
        self.url_entry.pack(padx=5, pady=5)

        self.destination_label = tk.Label(self.root, text="Destination Folder:")
        self.destination_label.pack(padx=5, pady=5)

        self.destination_entry = tk.Entry(self.root, width=50)
        self.destination_entry.pack(padx=5, pady=5)

        self.browse_button = tk.Button(self.root, text="Browse", command=self.browse_destination)
        self.browse_button.pack(padx=5, pady=5)

        self.download_button = tk.Button(self.root, text="Download", command=self.download_music)
        self.download_button.pack(pady=10)

        self.progress_bar = Progressbar(self.root, orient='horizontal', length=300, mode='determinate')
        self.progress_bar.pack(pady=20)

    def browse_destination(self):
        folder_selected = filedialog.askdirectory()
        if folder_selected:
            self.destination_entry.delete(0, tk.END)
            self.destination_entry.insert(0, folder_selected)

    def download_music(self):
        url = self.url_entry.get()
        destination = self.destination_entry.get()
        cfgObj = Cfg(directory=destination)

        if url and destination:
            try:
                self.progress_bar['value'] = 0
                self.root.update_idletasks()

                for i in range(1, 101):
                    self.progress_bar['value'] = i
                    self.root.update_idletasks()
                    time.sleep(0.03)

                run_gui(cfgObj, [url])
                messagebox.showinfo("Success", f"Music downloaded from {url} to {destination}")

            except Exception as e:
                messagebox.showerror("Error", f"An error occurred: {e}")
        else:
            messagebox.showwarning("Input error", "Please enter both URL and destination folder")

    def run(self):
        self.root.mainloop()
