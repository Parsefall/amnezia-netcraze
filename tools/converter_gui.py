"""Small offline desktop front end; tkinter is optional for CLI use."""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
import convert_profile as core

LABELS = {
 'ru': ['Amnezia → Netcraze: конвертер', 'Файл .vpn / .conf или ключ vpn:// (выберите один источник)', 'Выбрать файл', 'Выбрать файл с ключом или профилем', 'Вставьте ключ сюда, если файл не выбран:', 'Только IPv4: удалить IPv6 из адреса, DNS и AllowedIPs', 'Сохранить router.conf', 'Готово', 'Профиль сохранён. Исходник не изменён.\nИспользуйте этот профиль только на одном устройстве.\nУдалено IPv6-записей: ', 'Ошибка / Error', 'Выберите файл ИЛИ вставьте ключ, но не оба сразу.', 'Файл уже существует. Выберите другое имя.', 'Не удалось прочитать или записать файл. Проверьте путь и права.', 'Ключ не создаётся заново: это извлечение существующего клиентского профиля.\nОбработка локальная; отправки в Интернет нет.'],
 'en': ['Amnezia → Netcraze converter', '.vpn / .conf file OR vpn:// key (choose one source)', 'Choose file', 'Choose a key or profile file', 'Paste a key here if no file is selected:', 'IPv4 only: remove IPv6 from Address, DNS and AllowedIPs', 'Save router.conf', 'Done', 'Profile saved. Source unchanged.\nUse this client profile on one device only.\nRemoved IPv6 entries: ', 'Error', 'Choose a file OR paste a key, not both.', 'File already exists. Choose another name.', 'Unable to read or write the file. Check paths and permissions.', 'This extracts an existing client profile; it does not generate a new client.\nProcessing is offline; nothing is sent to the Internet.'],
}


def run(lang='ru'):
    l = LABELS[lang]
    root = tk.Tk()
    root.title(l[0])
    root.geometry('760x460')
    frame = ttk.Frame(root, padding=16)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text=l[1]).pack(anchor='w')
    row = ttk.Frame(frame)
    row.pack(fill='x', pady=8)
    source = tk.StringVar()
    ttk.Entry(row, textvariable=source).pack(side='left', fill='x', expand=True)
    def browse():
        path = filedialog.askopenfilename(title=l[3], filetypes=[('Amnezia profiles', '*.vpn *.conf *.txt'), ('All files', '*')])
        if path:
            source.set(path)
    ttk.Button(row, text=l[2], command=browse).pack(side='right', padx=8)
    ttk.Label(frame, text=l[4]).pack(anchor='w')
    key = tk.Text(frame, height=6, wrap='char')
    key.pack(fill='both', expand=True, pady=8)
    ipv4 = tk.BooleanVar(value=True)
    ttk.Checkbutton(frame, text=l[5], variable=ipv4).pack(anchor='w')
    ttk.Label(frame, text=l[13], wraplength=720).pack(anchor='w', pady=12)
    def save():
        path = source.get().strip()
        pasted = key.get('1.0', 'end').strip()
        if bool(path) == bool(pasted):
            messagebox.showerror(l[9], l[10]); return
        try:
            data = core.read_input(path) if path else pasted.encode('utf-8')
            result, removed = core.convert(data, ipv4_only=ipv4.get())
            destination = filedialog.asksaveasfilename(initialfile='router.conf', defaultextension='.conf', filetypes=[('AmneziaWG', '*.conf')])
            if not destination:
                return
            core.save_private(Path(destination), result)
            key.delete('1.0', 'end')
            messagebox.showinfo(l[7], l[8]+str(removed))
        except core.ConversionError as exc:
            messagebox.showerror(l[9], str(exc))
        except FileExistsError:
            messagebox.showerror(l[9], l[11])
        except (OSError, UnicodeError):
            messagebox.showerror(l[9], l[12])
    ttk.Button(frame, text=l[6], command=save).pack(anchor='e')
    root.mainloop()
