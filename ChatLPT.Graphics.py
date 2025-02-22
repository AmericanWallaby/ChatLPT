import tkinter as tk
from tkinter import ttk, messagebox, font, filedialog, simpledialog
import textwrap
import json
import threading
import os
import time
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageTk
from openai import OpenAI  # Legacy import style that works for your version

CONFIG_FILE = "chatlpt_config.json"

class ChatGPTTerminal:
    def __init__(self, root):
        self.root = root

        # Default settings
        self.api_key = None
        self.current_model = "gpt-3.5-turbo"
        self.font_family = "Consolas"
        self.custom_font_size = 16
        self.use_default_scaling = True
        self.default_font_size = 12  # windowed mode
        self.fullscreen = False
        self.image_display_mode = "inline"  # "inline" for ASCII, "crt" for CRT popup

        # Load persistent config if available.
        self.load_config()

        # Instantiate OpenAI client if API key is available.
        self.client = None
        if self.api_key:
            self.client = OpenAI(api_key=self.api_key)

        self.style = ttk.Style()
        self.default_tab_layout = self.style.layout("TNotebook.Tab")

        self.setup_menu()
        self.setup_tabs()
        self.setup_bindings()
        self.setup_tab_context_menu()

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    config = json.load(f)
                self.api_key = config.get("api_key", None)
                self.current_model = config.get("current_model", "gpt-3.5-turbo")
                self.font_family = config.get("font_family", "Consolas")
                self.custom_font_size = config.get("custom_font_size", 16)
                self.use_default_scaling = config.get("use_default_scaling", True)
                self.image_display_mode = config.get("image_display_mode", "inline")
            except Exception as e:
                messagebox.showerror("Config Error", f"Failed to load config: {e}")

    def save_config(self):
        config = {
            "api_key": self.api_key,
            "current_model": self.current_model,
            "font_family": self.font_family,
            "custom_font_size": self.custom_font_size,
            "use_default_scaling": self.use_default_scaling,
            "image_display_mode": self.image_display_mode
        }
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            messagebox.showerror("Config Error", f"Failed to save config: {e}")

    def on_closing(self):
        self.save_config()
        self.root.destroy()

    def setup_menu(self):
        self.menu_bar = tk.Menu(self.root)
        file_menu = tk.Menu(self.menu_bar, tearoff=0)
        file_menu.add_command(label="New Tab", command=self.create_new_tab)
        file_menu.add_command(label="Save Chat", command=self.save_chat)
        file_menu.add_command(label="Open Chat", command=self.open_chat)
        file_menu.add_command(label="Settings", command=self.open_settings)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        self.menu_bar.add_cascade(label="File", menu=file_menu)

        models_menu = tk.Menu(self.menu_bar, tearoff=0)
        models_menu.add_command(label="List Available GPT Models", command=self.list_models)
        self.menu_bar.add_cascade(label="Models", menu=models_menu)

        tools_menu = tk.Menu(self.menu_bar, tearoff=0)
        tools_menu.add_command(label="Clear Session", command=self.clear_session, accelerator="F3")
        self.menu_bar.add_cascade(label="Tools", menu=tools_menu)

        about_menu = tk.Menu(self.menu_bar, tearoff=0)
        about_menu.add_command(label="About ChatLPT...", command=self.about_dialog)
        self.menu_bar.add_cascade(label="About", menu=about_menu)

        self.root.config(menu=self.menu_bar)

    def setup_tabs(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True)
        self.create_new_tab()

    def setup_tab_context_menu(self):
        self.notebook.bind("<Button-3>", self.on_tab_right_click)

    def on_tab_right_click(self, event):
        try:
            index = self.notebook.index("@%d,%d" % (event.x, event.y))
            self.show_tab_context_menu(index, event)
        except tk.TclError:
            pass

    def show_tab_context_menu(self, index, event):
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Rename", command=lambda: self.rename_tab(index))
        menu.add_command(label="Close", command=lambda: self.close_tab(index))
        menu.tk_popup(event.x_root, event.y_root)

    def rename_tab(self, index):
        new_name = simpledialog.askstring("Rename Chat", "Enter new chat name:")
        if new_name:
            self.notebook.tab(index, text=new_name)

    def close_tab(self, index):
        tab_id = self.notebook.tabs()[index]
        tab_frame = self.notebook.nametowidget(tab_id)
        answer = messagebox.askyesnocancel("Close Chat", "Do you want to save the chat before closing?")
        if answer is None:
            return
        if answer:
            self.notebook.select(tab_frame)
            self.save_chat()
        if len(self.notebook.tabs()) == 1:
            self.root.destroy()
        else:
            self.notebook.forget(index)

    def create_new_tab(self, title="Chat"):
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text=title)
        text_area = tk.Text(frame, bg="black", fg="lime", insertbackground="lime",
                            wrap="word", undo=True)
        text_area.pack(fill="both", expand=True)
        text_area.config(font=(self.font_family, self.default_font_size))
        current_font = font.Font(font=text_area.cget("font"))
        cursor_width = current_font.measure("0") - 2
        if cursor_width < 1:
            cursor_width = 1
        text_area.config(insertwidth=cursor_width, insertontime=600, insertofftime=400)
        frame.text_area = text_area
        text_area.bind("<Alt-Return>", lambda e: self.toggle_fullscreen(e) or "break")
        frame.messages = [{"role": "system", "content": "You are a helpful assistant."}]
        self.insert_prompt(frame)
        text_area.bind("<Return>", lambda e, f=frame: self.on_return(e, f))
        text_area.bind("<Key>", lambda e, f=frame: self.on_key_press(e, f))
        text_area.bind("<Up>", lambda e, tw=text_area: self.scroll_text(e, tw, -1, "units"))
        text_area.bind("<Down>", lambda e, tw=text_area: self.scroll_text(e, tw, 1, "units"))
        text_area.bind("<Prior>", lambda e, tw=text_area: self.scroll_text(e, tw, -1, "pages"))
        text_area.bind("<Next>", lambda e, tw=text_area: self.scroll_text(e, tw, 1, "pages"))

    def insert_prompt(self, frame):
        text_area = frame.text_area
        if not text_area.get("end-2c", "end-1c").endswith("\n"):
            text_area.insert("end", "\n")
        text_area.insert("end", "> ")
        frame.cmd_start = text_area.index("end-1c")
        text_area.mark_set("insert", "end")

    def on_return(self, event, frame):
        text_area = frame.text_area
        command = text_area.get(frame.cmd_start, "end-1c").strip()
        if not command:
            return "break"

        text_area.insert("end", "\n")
        frame.messages.append({"role": "user", "content": command})

        if command.startswith("/image "):
            prompt = command[len("/image "):].strip()
            text_area.insert("end", "[Generating image...]\n")
            text_area.see("end")
            threading.Thread(target=self.process_image_command, args=(frame, prompt), daemon=True).start()
        else:
            text_area.insert("end", "[Thinking...]\n")
            text_area.see("end")
            threading.Thread(target=self.process_gpt_response, args=(frame,), daemon=True).start()
        return "break"

    def process_gpt_response(self, frame):
        try:
            response = self.client.chat.completions.create(
                model=self.current_model,
                messages=frame.messages,
                temperature=0.8
            )
            response_text = response.choices[0].message.content.strip()
        except Exception as e:
            response_text = f"Error: {e}"
        processed_text = self.preprocess_text(response_text)
        frame.messages.append({"role": "assistant", "content": response_text})
        frame.text_area.after(0, lambda: self.update_response(frame, processed_text))

    def process_image_command(self, frame, prompt):
        try:
            if not self.api_key:
                raise Exception("API key not provided. Please set your API key in Settings.")
            # Ensure the client is set up.
            if not self.client:
                self.client = OpenAI(api_key=self.api_key)
            response = self.client.Image.create(
                prompt=prompt,
                n=1,
                size="512x512",
                model="image-alpha-001"
            )
            image_url = response['data'][0]['url']
            r = requests.get(image_url)
            img = Image.open(BytesIO(r.content))
            if self.image_display_mode == "inline":
                ascii_art = self.generate_ascii_art(img)
                frame.messages.append({"role": "assistant", "content": ascii_art})
                frame.text_area.after(0, lambda: self.update_response(frame, ascii_art))
            elif self.image_display_mode == "crt":
                frame.text_area.after(0, lambda: self.show_crt_popup(img))
                notification = f"[Image generated in CRT Popup for: {prompt}]"
                frame.messages.append({"role": "assistant", "content": notification})
                frame.text_area.after(0, lambda: self.update_response(frame, notification))
        except Exception as e:
            error_message = f"Error generating image: {e}"
            frame.messages.append({"role": "assistant", "content": error_message})
            frame.text_area.after(0, lambda: self.update_response(frame, error_message))

    def generate_ascii_art(self, img, new_width=80):
        img = img.convert("L")
        width, height = img.size
        aspect_ratio = height / width
        new_height = int(aspect_ratio * new_width * 0.55)
        img = img.resize((new_width, new_height))
        ascii_chars = "@%#*+=-:. "
        pixels = img.getdata()
        ascii_str = ""
        for i, pixel in enumerate(pixels):
            ascii_str += ascii_chars[int(pixel / 256 * len(ascii_chars))]
            if (i + 1) % new_width == 0:
                ascii_str += "\n"
        return ascii_str

    def show_crt_popup(self, img):
        popup = tk.Toplevel(self.root)
        popup.title("CRT Image Display")
        popup.configure(bg="black")
        popup.geometry("512x512")
        photo = ImageTk.PhotoImage(img)
        label = tk.Label(popup, image=photo, bg="black")
        label.image = photo  # Keep reference to avoid garbage collection.
        label.pack(expand=True)
        popup.after(5000, popup.destroy)

    def update_response(self, frame, processed_text):
        text_area = frame.text_area
        current_text = text_area.get("1.0", tk.END)
        current_text = current_text.replace("[Thinking...]\n", "").replace("[Generating image...]\n", "")
        text_area.delete("1.0", tk.END)
        text_area.insert("1.0", current_text)
        text_area.insert(tk.END, f"{processed_text}\n")
        self.insert_prompt(frame)
        text_area.see("end")

    def on_key_press(self, event, frame):
        text_area = frame.text_area
        if text_area.compare("insert", "<", frame.cmd_start):
            text_area.mark_set("insert", frame.cmd_start)
        if event.keysym == "BackSpace" and text_area.compare("insert", "==", frame.cmd_start):
            return "break"
        return None

    def scroll_text(self, event, text_area, amount, unit):
        text_area.yview_scroll(amount, unit)
        text_area.mark_set("insert", text_area.index("end-1c"))
        return "break"

    def open_settings(self):
        settings = tk.Toplevel(self.root)
        settings.title("Settings")
        settings.grab_set()

        tk.Label(settings, text="Enter ChatGPT API Key:").grid(row=0, column=0, padx=10, pady=5, sticky="w")
        api_entry = tk.Entry(settings, width=50)
        api_entry.grid(row=0, column=1, padx=10, pady=5)
        if self.api_key:
            api_entry.insert(0, self.api_key)

        tk.Label(settings, text="Font Scaling:").grid(row=1, column=0, padx=10, pady=5, sticky="w")
        scaling_mode = tk.StringVar(value="default" if self.use_default_scaling else "custom")
        def toggle_custom_entry():
            custom_entry.config(state="normal" if scaling_mode.get() == "custom" else "disabled")
        default_rb = tk.Radiobutton(settings, text="Default Scaling", variable=scaling_mode,
                                    value="default", command=toggle_custom_entry)
        default_rb.grid(row=2, column=1, sticky="w", padx=10, pady=2)
        custom_rb = tk.Radiobutton(settings, text="Custom Font Size:", variable=scaling_mode,
                                   value="custom", command=toggle_custom_entry)
        custom_rb.grid(row=3, column=1, sticky="w", padx=10, pady=2)
        custom_entry = tk.Entry(settings, width=10)
        custom_entry.grid(row=3, column=1, padx=150, pady=2, sticky="w")
        custom_entry.insert(0, str(self.custom_font_size))
        if scaling_mode.get() == "default":
            custom_entry.config(state="disabled")

        tk.Label(settings, text="Font Family:").grid(row=4, column=0, padx=10, pady=5, sticky="w")
        fonts = sorted(font.families())
        font_var = tk.StringVar(value=self.font_family)
        font_combo = ttk.Combobox(settings, textvariable=font_var, values=fonts, state="readonly")
        font_combo.grid(row=4, column=1, padx=10, pady=5, sticky="w")

        tk.Label(settings, text="Image Display Mode:").grid(row=5, column=0, padx=10, pady=5, sticky="w")
        image_mode = tk.StringVar(value=self.image_display_mode)
        inline_rb = tk.Radiobutton(settings, text="Inline ASCII", variable=image_mode, value="inline")
        inline_rb.grid(row=5, column=1, sticky="w", padx=10, pady=2)
        crt_rb = tk.Radiobutton(settings, text="CRT Popup", variable=image_mode, value="crt")
        crt_rb.grid(row=6, column=1, sticky="w", padx=10, pady=2)

        def save_settings():
            self.api_key = api_entry.get().strip()
            if scaling_mode.get() == "default":
                self.use_default_scaling = True
            else:
                self.use_default_scaling = False
                try:
                    size = int(custom_entry.get().strip())
                    if size < 8:
                        raise ValueError
                    self.custom_font_size = size
                except ValueError:
                    messagebox.showerror("Error", "Please enter a valid font size (number >= 8).")
                    return
            self.font_family = font_var.get()
            self.image_display_mode = image_mode.get()
            settings.destroy()
            self.update_all_tabs_font()
            self.save_config()

        tk.Button(settings, text="Save", command=save_settings).grid(row=7, column=0, columnspan=2, pady=10)

    def clear_session(self, event=None):
        try:
            current_tab = self.notebook.nametowidget(self.notebook.select())
        except tk.TclError:
            messagebox.showerror("Error", "No chat tab is active.")
            return
        answer = messagebox.askyesno("Clear Session", "Are you sure you want to clear the current session? This cannot be undone.")
        if not answer:
            return
        current_tab.messages = [{"role": "system", "content": "You are a helpful assistant."}]
        current_tab.text_area.delete("1.0", tk.END)
        self.insert_prompt(current_tab)

    def save_chat(self):
        try:
            current_tab = self.notebook.nametowidget(self.notebook.select())
        except tk.TclError:
            messagebox.showerror("Error", "No chat tab is active.")
            return
        tab_text = self.notebook.tab(self.notebook.select(), "text")
        default_filename = f"{tab_text}.lpt"
        file_path = filedialog.asksaveasfilename(
            title="Save Chat",
            defaultextension=".lpt",
            initialfile=default_filename,
            filetypes=[("ChatLPT Files", "*.lpt"), ("All Files", "*.*")]
        )
        if not file_path:
            return
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(current_tab.messages, f, indent=2)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save chat: {e}")

    def open_chat(self):
        file_path = filedialog.askopenfilename(
            title="Open Chat",
            filetypes=[("ChatLPT Files", "*.lpt"), ("All Files", "*.*")]
        )
        if not file_path:
            return
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                messages = json.load(f)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open chat: {e}")
            return
        new_tab = ttk.Frame(self.notebook)
        tab_name = os.path.basename(file_path).rsplit(".", 1)[0]
        self.notebook.add(new_tab, text=tab_name)
        text_area = tk.Text(new_tab, bg="black", fg="lime", insertbackground="lime",
                            wrap="word", undo=True)
        text_area.pack(fill="both", expand=True)
        text_area.config(font=(self.font_family, self.default_font_size))
        current_font = font.Font(font=text_area.cget("font"))
        text_area.config(insertwidth=current_font.measure("0"), insertontime=600, insertofftime=400)
        new_tab.text_area = text_area
        new_tab.messages = messages
        text_area.delete("1.0", tk.END)
        for msg in messages:
            if msg["role"] == "user":
                text_area.insert(tk.END, f"> {msg['content']}\n")
            else:
                wrapped = self.preprocess_text(msg["content"])
                text_area.insert(tk.END, f"{wrapped}\n")
        self.insert_prompt(new_tab)
        self.notebook.select(new_tab)
        text_area.bind("<Alt-Return>", lambda e: self.toggle_fullscreen(e) or "break")
        text_area.bind("<Return>", lambda e, f=new_tab: self.on_return(e, f))
        text_area.bind("<Key>", lambda e, f=new_tab: self.on_key_press(e, f))
        text_area.bind("<Up>", lambda e, tw=text_area: self.scroll_text(e, tw, -1, "units"))
        text_area.bind("<Down>", lambda e, tw=text_area: self.scroll_text(e, tw, 1, "units"))
        text_area.bind("<Prior>", lambda e, tw=text_area: self.scroll_text(e, tw, -1, "pages"))
        text_area.bind("<Next>", lambda e, tw=text_area: self.scroll_text(e, tw, 1, "pages"))

    def list_models(self):
        threading.Thread(target=self._list_models_thread, daemon=True).start()

    def _list_models_thread(self):
        if not self.api_key:
            self.root.after(0, lambda: messagebox.showerror("Error", "API key is not provided. Please set your API key in Settings."))
            return
        try:
            models = self.client.models.list()
            model_list = [m.id for m in models.data if "gpt" in m.id.lower()]
            self.root.after(0, lambda: self.show_model_list(model_list))
        except Exception as ex:
            self.root.after(0, lambda: messagebox.showerror("Error", f"Failed to list models: {ex}"))

    def show_model_list(self, model_list):
        win = tk.Toplevel(self.root)
        win.title("Available GPT Models")
        listbox = tk.Listbox(win, width=50, height=20)
        listbox.pack(side="left", fill="both", expand=True)
        scrollbar = tk.Scrollbar(win)
        scrollbar.pack(side="right", fill="y")
        listbox.config(yscrollcommand=scrollbar.set)
        scrollbar.config(command=listbox.yview)
        for m in model_list:
            listbox.insert(tk.END, m)
        def select_model():
            try:
                selection = listbox.get(listbox.curselection())
                self.current_model = selection
                messagebox.showinfo("Model Selected", f"Selected model: {selection}")
                win.destroy()
            except Exception as ex:
                messagebox.showerror("Selection Error", "No model selected.")
        select_button = tk.Button(win, text="Select Model", command=select_model)
        select_button.pack(pady=10)

    def about_dialog(self):
        about_win = tk.Toplevel(self.root)
        about_win.title("About ChatLPT")
        about_win.resizable(False, False)
        main_frame = tk.Frame(about_win, bg="white")
        main_frame.pack(padx=10, pady=10)
        left_frame = tk.Frame(main_frame, bg="white")
        left_frame.pack(side="left", padx=10, pady=10)
        label_title = tk.Label(left_frame, text="ChatLPT Graphics", font=("Helvetica", 34, "italic"), bg="white")
        label_title.pack()
        label_release = tk.Label(left_frame, text="Release Candidate v. 0.9", font=("Helvetica", 20), bg="white")
        label_release.pack()
        label_copyright = tk.Label(left_frame, text="(c) 2025 americanwallaby", font=("Helvetica", 18), bg="white")
        label_copyright.pack()
        right_frame = tk.Frame(main_frame, bg="white")
        right_frame.pack(side="right", padx=10, pady=10)
        canvas = tk.Canvas(right_frame, width=150, height=150, bg="white", highlightthickness=0)
        canvas.pack()
        self.icon1_img = tk.PhotoImage(file="about1.png")
        self.icon2_img = tk.PhotoImage(file="about2.png")
        icon1 = canvas.create_image(10, 10, image=self.icon1_img, anchor='nw')
        icon2 = canvas.create_image(50, 50, image=self.icon2_img, anchor='nw')
        quote_label = tk.Label(right_frame, text='"Is it real, or is it a muffin?"',
                               font=("Helvetica", 8, "italic", "bold"), bg="white")
        quote_label.pack(pady=5)
        ok_button = tk.Button(about_win, text="OK", command=about_win.destroy)
        ok_button.pack(pady=10)
        self.animate_icons(canvas, icon1, icon2)

    def animate_icons(self, canvas, icon1, icon2):
        w1, h1 = self.icon1_img.width(), self.icon1_img.height()
        w2, h2 = self.icon2_img.width(), self.icon2_img.height()
        state = {
            "icon1_dx": 2, "icon1_dy": 2,
            "icon2_dx": -2, "icon2_dy": 3,
        }
        def update():
            coords = canvas.coords(icon1)
            x, y = coords[0], coords[1]
            if x <= 0 or x + w1 >= 150:
                state["icon1_dx"] = -state["icon1_dx"]
            if y <= 0 or y + h1 >= 150:
                state["icon1_dy"] = -state["icon1_dy"]
            canvas.move(icon1, state["icon1_dx"], state["icon1_dy"])
            coords = canvas.coords(icon2)
            x, y = coords[0], coords[1]
            if x <= 0 or x + w2 >= 150:
                state["icon2_dx"] = -state["icon2_dx"]
            if y <= 0 or y + h2 >= 150:
                state["icon2_dy"] = -state["icon2_dy"]
            canvas.move(icon2, state["icon2_dx"], state["icon2_dy"])
            canvas.after(50, update)
        update()

    def setup_bindings(self):
        self.root.bind_all("<Alt-Return>", self.toggle_fullscreen)
        self.root.bind_all("<F3>", self.clear_session)

    def toggle_fullscreen(self, event=None):
        self.fullscreen = not self.fullscreen
        self.root.attributes("-fullscreen", self.fullscreen)
        if self.fullscreen:
            self.root.config(menu="")
            self.root.overrideredirect(True)
            self.style.layout("TNotebook.Tab", [])
        else:
            self.root.config(menu=self.menu_bar)
            self.root.overrideredirect(False)
            self.style.layout("TNotebook.Tab", self.default_tab_layout)
        self.update_all_tabs_font()
        self.root.focus_force()

    def update_all_tabs_font(self):
        if self.fullscreen:
            if self.use_default_scaling:
                screen_width = self.root.winfo_screenwidth()
                screen_height = self.root.winfo_screenheight()
                char_width = screen_width / 80
                char_height = screen_height / 25
                new_size = int(min(char_width, char_height)) - 2
                new_size = max(new_size, 8)
            else:
                new_size = self.custom_font_size
        else:
            new_size = self.default_font_size if self.use_default_scaling else self.custom_font_size
        for tab_id in self.notebook.tabs():
            frame = self.notebook.nametowidget(tab_id)
            frame.text_area.config(font=(self.font_family, new_size))
            current_font = font.Font(font=frame.text_area.cget("font"))
            frame.text_area.config(insertwidth=current_font.measure("0") - 2)

    def preprocess_text(self, text, width=80):
        return text

    def get_chatgpt_response(self, messages):
        if not self.api_key:
            return "Error: API key is not provided. Please set your API key in Settings."
        try:
            response = self.client.chat.completions.create(
                model=self.current_model,
                messages=messages,
                temperature=0.8
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            return f"Error: {e}"

if __name__ == "__main__":
    root = tk.Tk()
    root.title("ChatLPT Graphics")
    app = ChatGPTTerminal(root)
    root.mainloop()
