"""Fenetre de l'application (Tkinter) : la meme logique que l'ancienne page web, en natif."""
import asyncio
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import env

BG, PANEL, FIELD, LINE = '#17191d', '#1d2126', '#111317', '#2e343c'
TXT, DIM, ACC = '#e8eaed', '#98a1ad', '#ff8a3d'
OK, BAD = '#6fdc8c', '#ff6b6b'
BTN, BTN_HOT = '#2b3038', '#3a414c'


class Gui(tk.Tk):
    def __init__(self, app, loop_ready, thread):
        super().__init__()
        self.app = app
        self.thread = thread
        self.loop_ready = loop_ready
        self.title('FL Cowork')
        self.geometry('660x800')
        self.minsize(560, 640)
        self.protocol('WM_DELETE_WINDOW', self.on_close)
        self.theme()
        self.pending = []          # (futur, rappel)
        self.mode = None
        self.chat_n = (-1, 0)
        self.peer_sig = None
        self.err = tk.StringVar()
        self.build()
        self.after(100, self.tick)

    # ----------------------------------------------------------- theme sombre
    def theme(self):
        self.configure(bg=BG)
        st = ttk.Style(self)
        st.theme_use('clam')
        F = ('Segoe UI', 9)
        st.configure('.', background=BG, foreground=TXT, fieldbackground=FIELD, bordercolor=LINE,
                     lightcolor=BG, darkcolor=BG, troughcolor=FIELD, font=F, focuscolor=BG)
        st.configure('TFrame', background=BG)
        st.configure('TLabel', background=BG, foreground=TXT)
        st.configure('Dim.TLabel', foreground=DIM)
        st.configure('Title.TLabel', font=('Segoe UI', 10, 'bold'))
        st.configure('Ok.TLabel', foreground=OK)
        st.configure('Bad.TLabel', foreground=BAD)
        st.configure('TLabelframe', background=BG, bordercolor=LINE, lightcolor=BG, darkcolor=BG, relief='solid')
        st.configure('TLabelframe.Label', background=BG, foreground=DIM, font=('Segoe UI', 8, 'bold'))
        st.configure('Card.TFrame', background=PANEL)
        for w in ('Card.TLabel',):
            st.configure(w, background=PANEL)
        st.configure('TButton', background=BTN, foreground=TXT, bordercolor=LINE, lightcolor=BTN, darkcolor=BTN,
                     padding=(10, 5), relief='flat')
        st.map('TButton', background=[('disabled', BG), ('active', BTN_HOT)], foreground=[('disabled', '#5b626c')],
               bordercolor=[('focus', ACC)])
        st.configure('Big.TButton', background=ACC, foreground='#1b1206', bordercolor=ACC, lightcolor=ACC, darkcolor=ACC,
                     padding=(16, 7), font=('Segoe UI', 9, 'bold'))
        st.map('Big.TButton', background=[('disabled', '#6b4a2d'), ('active', '#ff9d5c')],
               foreground=[('disabled', '#2a2118')])
        st.configure('TEntry', fieldbackground=FIELD, foreground=TXT, insertcolor=TXT, bordercolor=LINE,
                     lightcolor=FIELD, darkcolor=FIELD, padding=5)
        st.map('TEntry', bordercolor=[('focus', ACC)], lightcolor=[('focus', ACC)], darkcolor=[('focus', ACC)],
               fieldbackground=[('readonly', FIELD)], foreground=[('readonly', TXT)])
        st.configure('TCheckbutton', background=BG, foreground=TXT, indicatorbackground=FIELD,
                     indicatorforeground=ACC, bordercolor=LINE)
        st.map('TCheckbutton', background=[('active', BG)], indicatorbackground=[('selected', ACC)])
        st.configure('Treeview', background=FIELD, fieldbackground=FIELD, foreground=TXT, bordercolor=LINE, rowheight=24)
        st.configure('Treeview.Heading', background=PANEL, foreground=DIM, bordercolor=LINE, relief='flat',
                     font=('Segoe UI', 8, 'bold'))
        st.map('Treeview', background=[('selected', '#3a2f26')], foreground=[('selected', TXT)])
        st.map('Treeview.Heading', background=[('active', PANEL)])
        st.configure('TNotebook', background=BG, bordercolor=LINE, lightcolor=BG, darkcolor=BG, tabmargins=(0, 0, 0, 0))
        st.configure('TNotebook.Tab', background=BTN, foreground=DIM, padding=(10, 6), bordercolor=LINE,
                     lightcolor=BTN, darkcolor=BTN, font=('Segoe UI', 9, 'bold'))
        st.map('TNotebook.Tab', background=[('selected', ACC), ('active', BTN_HOT)],
               foreground=[('selected', '#1b1206'), ('active', TXT)])
        st.configure('TRadiobutton', background=BG, foreground=TXT, indicatorbackground=FIELD, indicatorforeground=ACC)
        st.map('TRadiobutton', background=[('active', BG)], indicatorbackground=[('selected', ACC)])
        st.configure('Horizontal.TProgressbar', background=ACC, troughcolor=FIELD, bordercolor=LINE,
                     lightcolor=ACC, darkcolor=ACC)
        st.configure('Vertical.TScrollbar', background=BTN, troughcolor=FIELD, bordercolor=FIELD,
                     arrowcolor=DIM, lightcolor=BTN, darkcolor=BTN)
        try:
            self.logo = tk.PhotoImage(file=env.resource('icon.png'))
            self.iconphoto(True, self.logo)
        except tk.TclError:
            self.logo = None
        self.bind('<Map>', lambda _e: self.after(30, self.dark_titlebar), add='+')
        self.after(200, self.dark_titlebar)

    def dark_titlebar(self):
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            v = ctypes.c_int(1)
            for attr in (20, 19):
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), 4)
            # force le redessin de la barre de titre
            ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0020)
        except Exception:
            pass

    # ----------------------------------------------------------- construction
    def build(self):
        root = ttk.Frame(self, padding=14)
        root.pack(fill='both', expand=True)
        top = ttk.Frame(root)
        top.pack(fill='x')
        if self.logo:
            ttk.Label(top, image=self.logo).pack(side='left', padx=(0, 10))
        ttk.Label(top, text='FL Cowork', font=('Segoe UI', 15, 'bold')).pack(side='left')
        self.fl_lbl = ttk.Label(top, text='FL Studio : ...')
        self.fl_lbl.pack(side='right')
        ttk.Label(root, textvariable=self.err, style='Bad.TLabel', wraplength=520).pack(fill='x', pady=(6, 0))

        name = ttk.Frame(root)
        name.pack(fill='x', pady=(8, 0))
        ttk.Label(name, text='Votre nom').pack(side='left')
        self.name = tk.StringVar()
        e = self.name_entry = ttk.Entry(name, textvariable=self.name, width=26)
        e.pack(side='left', padx=8)
        e.bind('<FocusOut>', lambda _e: self.call('name', value=self.name.get()))
        e.bind('<Return>', lambda _e: self.call('name', value=self.name.get()))

        self.lobby = ttk.Frame(root)
        self.session = ttk.Frame(root)
        self.build_lobby()
        self.build_session()

    def build_lobby(self):
        f = self.lobby
        self.slot = ttk.Frame(f)
        self.slot.pack(fill='x')
        box = ttk.LabelFrame(self.slot, text='Mise en route', padding=10)
        box.pack(fill='x', pady=(12, 0))
        self.chk = {}
        for key, txt in (('script', 'Script FL Studio installé'), ('midi', 'Port MIDI virtuel « FL Cowork »'),
                         ('fl', 'FL Studio connecté')):
            lbl = ttk.Label(box, text='○  ' + txt)
            lbl.pack(anchor='w')
            self.chk[key] = (lbl, txt)
        self.help = ttk.Label(box, style='Dim.TLabel', wraplength=500, justify='left',
                              text='Dans FL Studio, une seule fois : Options › MIDI settings › Input › « FL Cowork » › '
                                   'Controller type « FL Cowork » › Enable.')
        self.help.pack(anchor='w', pady=(4, 0))
        self.fix = ttk.Button(box, text="Réparer l'installation", command=lambda: self.call('setup'))
        self.box = box

        host = ttk.LabelFrame(f, text='Héberger une session', padding=10)
        host.pack(fill='x', pady=(12, 0))
        r = ttk.Frame(host)
        r.pack(fill='x')
        self.path = tk.StringVar()
        ttk.Entry(r, textvariable=self.path).pack(side='left', fill='x', expand=True)
        ttk.Button(r, text='Parcourir…', command=self.browse).pack(side='left', padx=(6, 0))
        ttk.Label(host, text='Projet .flp existant. Laisser vide pour partir d\'un projet vide.',
                  style='Dim.TLabel').pack(anchor='w', pady=(2, 8))
        r = ttk.Frame(host)
        r.pack(fill='x')
        ttk.Label(r, text='Nom du nouveau projet').pack(side='left')
        self.pname = tk.StringVar()
        ttk.Entry(r, textvariable=self.pname).pack(side='left', fill='x', expand=True, padx=(8, 0))
        self.host_btn = ttk.Button(host, text='Créer la session', style='Big.TButton', command=self.do_host)
        self.host_btn.pack(anchor='e', pady=(10, 0))

        join = ttk.LabelFrame(f, text='Rejoindre une session', padding=10)
        join.pack(fill='x', pady=(12, 0))
        r = ttk.Frame(join)
        r.pack(fill='x')
        self.code = tk.StringVar()
        e = ttk.Entry(r, textvariable=self.code)
        e.pack(side='left', fill='x', expand=True)
        e.bind('<Return>', lambda _e: self.do_join())
        self.join_btn = ttk.Button(r, text='Rejoindre', style='Big.TButton', command=self.do_join)
        self.join_btn.pack(side='left', padx=(6, 0))
        ttk.Label(join, text='Collez le code FLC-… reçu de l\'hôte.', style='Dim.TLabel').pack(anchor='w', pady=(2, 0))

    def build_session(self):
        f = self.session
        top = ttk.LabelFrame(f, text='État', padding=10)
        top.pack(fill='x', pady=(12, 0))
        self.st_title = ttk.Label(top, text='', style='Title.TLabel', wraplength=540)
        self.st_title.pack(anchor='w')
        self.st_sub = ttk.Label(top, text='', style='Dim.TLabel', wraplength=540)
        self.st_sub.pack(anchor='w')
        self.bar = ttk.Progressbar(top, maximum=100)
        r = ttk.Frame(top)
        r.pack(fill='x', pady=(8, 0))
        self.btn_send = ttk.Button(r, text='Envoyer et fusionner', command=lambda: self.call('publish'))
        self.btn_send.pack(side='left')
        self.btn_load = ttk.Button(r, text='Charger la version', command=lambda: self.call('reload'))
        self.btn_load.pack(side='left', padx=6)
        ttk.Button(r, text='Quitter la session', command=self.leave).pack(side='right')

        self.nb = ttk.Notebook(f)
        self.nb.pack(fill='both', expand=True, pady=(12, 0))
        self.tab_changes = ttk.Frame(self.nb, padding=10)
        self.tab_hist = ttk.Frame(self.nb, padding=10)
        self.tab_team = ttk.Frame(self.nb, padding=10)
        self.tab_invite = ttk.Frame(self.nb, padding=10)
        self.nb.add(self.tab_changes, text='  Changements  ')
        self.nb.add(self.tab_hist, text='  Historique  ')
        self.nb.add(self.tab_team, text='  Équipe  ')
        self.nb.add(self.tab_invite, text='  Inviter  ')
        self.invite_shown = True

        # ---- onglet Changements
        t = self.tab_changes
        mode = ttk.LabelFrame(t, text='Mode', padding=10)
        mode.pack(fill='x')
        self.mode_var = tk.StringVar(value='auto')
        for val, txt, hint in (
                ('auto', 'Automatique', 'Ctrl+S envoie et fusionne tout de suite ; les versions reçues se chargent seules.'),
                ('manual', 'Manuel (validation)', 'Ctrl+S enregistre en local. Vous relisez le résumé des changements reçus, '
                                                  'puis vous les appliquez et envoyez les vôtres quand vous voulez.')):
            ttk.Radiobutton(mode, text=txt, value=val, variable=self.mode_var,
                            command=lambda: self.call('mode', value=self.mode_var.get())).pack(anchor='w')
            ttk.Label(mode, text=hint, style='Dim.TLabel', wraplength=520, justify='left').pack(anchor='w', padx=(22, 0), pady=(0, 4))

        self.in_card = ttk.LabelFrame(t, text='Changements reçus', padding=10)
        self.in_head = ttk.Label(self.in_card, text='', style='Title.TLabel', wraplength=520)
        self.in_head.pack(anchor='w')
        self.in_text = self.make_text(self.in_card, 4)
        r = ttk.Frame(self.in_card)
        r.pack(fill='x', pady=(6, 0))
        ttk.Button(r, text='Appliquer (fusionner)', style='Big.TButton', command=lambda: self.call('reload')).pack(side='left')
        ttk.Button(r, text='Ignorer', command=lambda: self.call('ignore')).pack(side='left', padx=6)

        self.out_card = ttk.LabelFrame(t, text='Mes modifications non envoyées', padding=10)
        self.out_text = self.make_text(self.out_card, 4)
        r = ttk.Frame(self.out_card)
        r.pack(fill='x', pady=(6, 0))
        self.commit_msg = tk.StringVar()
        e = ttk.Entry(r, textvariable=self.commit_msg)
        e.pack(side='left', fill='x', expand=True)
        ttk.Button(r, text='Envoyer', style='Big.TButton', command=self.commit).pack(side='left', padx=(6, 0))
        ttk.Label(self.out_card, text='Message de version (facultatif)', style='Dim.TLabel').pack(anchor='w')

        adv = self.adv_card = ttk.LabelFrame(t, text='Avancé', padding=10)
        adv.pack(fill='x', pady=(10, 0))
        self.cards_state = None
        r = ttk.Frame(adv)
        r.pack(fill='x')
        ttk.Button(r, text='Imposer ma version', command=self.force_send).pack(side='left')
        ttk.Button(r, text='Prendre leur version', command=self.force_recv).pack(side='left', padx=6)
        ttk.Label(r, text='sans fusion', style='Dim.TLabel').pack(side='left')
        r = ttk.Frame(adv)
        r.pack(fill='x', pady=(6, 0))
        ttk.Button(r, text='Dossier de la session', command=lambda: self.call('folder')).pack(side='left')
        ttk.Button(r, text='Journal', command=lambda: self.call('open_log')).pack(side='left', padx=6)
        self.autoload = tk.BooleanVar()
        ttk.Checkbutton(adv, text='Charger automatiquement les nouvelles versions (mode automatique)', variable=self.autoload,
                        command=lambda: self.call('set', key='autoload', value=self.autoload.get())).pack(anchor='w', pady=(8, 0))

        # ---- onglet Historique
        h = self.tab_hist
        self.hist = ttk.Treeview(h, columns=('who', 'when', 'msg'), show='tree headings', height=10)
        self.hist.heading('#0', text='N°')
        self.hist.heading('who', text='Auteur')
        self.hist.heading('when', text='Heure')
        self.hist.heading('msg', text='Message')
        self.hist.column('#0', width=60, stretch=False)
        self.hist.column('who', width=110, stretch=False)
        self.hist.column('when', width=110, stretch=False)
        self.hist.column('msg', width=260)
        sb = ttk.Scrollbar(h, command=self.hist.yview)
        self.hist.configure(yscrollcommand=sb.set)
        sb.pack(side='right', fill='y')
        self.hist.pack(fill='both', expand=True)
        r = ttk.Frame(self.tab_hist)
        ttk.Button(r, text='Restaurer cette version', command=self.restore).pack(side='left')
        ttk.Label(r, text='Crée une nouvelle version identique à l\'ancienne ; rien n\'est effacé.',
                  style='Dim.TLabel').pack(side='left', padx=8)
        r.pack(fill='x', pady=(8, 0), side='bottom')
        self.hist_sig = None

        # ---- onglet Équipe
        pe = ttk.LabelFrame(self.tab_team, text='Participants', padding=10)
        pe.pack(fill='x')
        self.peers = ttk.Treeview(pe, columns=('fl', 'where'), show='tree headings', height=2)
        self.peers.heading('#0', text='Nom')
        self.peers.heading('fl', text='FL Studio')
        self.peers.heading('where', text='Fenêtre')
        self.peers.column('#0', width=190)
        self.peers.column('fl', width=100)
        self.peers.column('where', width=140)
        self.peers.pack(fill='x')
        ch = ttk.LabelFrame(self.tab_team, text='Discussion et journal', padding=10)
        ch.pack(fill='both', expand=True, pady=(10, 0))
        self.chat = tk.Text(ch, height=8, state='disabled', wrap='word', relief='flat', background=FIELD,
                            foreground=TXT, insertbackground=TXT, highlightthickness=0, padx=8, pady=6,
                            font=('Segoe UI', 9))
        sb = ttk.Scrollbar(ch, command=self.chat.yview)
        self.chat.configure(yscrollcommand=sb.set)
        self.chat.tag_configure('sys', foreground=DIM)
        self.chat.tag_configure('who', font=('Segoe UI', 9, 'bold'), foreground=ACC)
        sb.pack(side='right', fill='y')
        self.chat.pack(fill='both', expand=True)
        r = ttk.Frame(self.tab_team)
        r.pack(fill='x', pady=(6, 0))
        self.msg = tk.StringVar()
        e = ttk.Entry(r, textvariable=self.msg)
        e.pack(side='left', fill='x', expand=True)
        e.bind('<Return>', lambda _e: self.send_chat())
        ttk.Button(r, text='Envoyer', command=self.send_chat).pack(side='left', padx=(6, 0))

        # ---- onglet Inviter
        self.codes = self.tab_invite
        self.code_vars = {}
        for key, txt in (('vpn', 'VPN (Radmin, Hamachi, Tailscale)'), ('lan', 'Même réseau local'), ('wan', 'Internet')):
            row = ttk.Frame(self.codes)
            ttk.Label(row, text=txt, style='Dim.TLabel').pack(anchor='w')
            line = ttk.Frame(row)
            line.pack(fill='x')
            v = tk.StringVar()
            ttk.Entry(line, textvariable=v, state='readonly').pack(side='left', fill='x', expand=True)
            ttk.Button(line, text='Copier', width=8, command=lambda v=v: self.copy(v.get())).pack(side='left', padx=(6, 0))
            self.code_vars[key] = (row, v)
        self.ipbox = ttk.Frame(self.codes)
        ttk.Label(self.ipbox, style='Dim.TLabel', wraplength=540, justify='left',
                  text='Internet : ouverture automatique du port impossible. Redirigez le port TCP sur votre box, '
                       'puis générez un code avec votre adresse IP publique (ou VPN) :').pack(anchor='w')
        r = ttk.Frame(self.ipbox)
        r.pack(fill='x', pady=(4, 0))
        self.ip = tk.StringVar()
        ttk.Entry(r, textvariable=self.ip, width=20).pack(side='left')
        ttk.Button(r, text='Générer', command=self.gen_code).pack(side='left', padx=6)
        self.gen_var = tk.StringVar()
        self.gen_entry = ttk.Entry(self.ipbox, textvariable=self.gen_var, state='readonly')

    def make_text(self, parent, height):
        t = tk.Text(parent, height=height, state='disabled', wrap='word', relief='flat', background=FIELD,
                    foreground=TXT, highlightthickness=0, padx=8, pady=6, font=('Segoe UI', 9))
        t.pack(fill='x', pady=(4, 0))
        return t

    @staticmethod
    def set_text(widget, lines):
        widget.configure(state='normal')
        widget.delete('1.0', 'end')
        widget.insert('end', '\n'.join('•  ' + x for x in lines))
        widget.configure(state='disabled')

    # ------------------------------------------------------------- actions
    def call(self, op, done=None, **kw):
        """Lance une action dans la boucle de l'application ; le resultat est repris dans tick()."""
        if self.app.loop is None:
            return
        kw['op'] = op
        fut = asyncio.run_coroutine_threadsafe(self.app.act(kw), self.app.loop)
        self.pending.append((fut, done))

    def browse(self):
        p = filedialog.askopenfilename(title='Choisir le projet à partager',
                                       filetypes=[('Projets FL Studio', '*.flp')])
        if p:
            self.path.set(p.replace('/', '\\'))

    def do_host(self):
        self.err.set('')
        self.host_btn.state(['disabled'])
        self.call('host', path=self.path.get().strip(), name=self.pname.get().strip())

    def do_join(self):
        self.err.set('')
        self.join_btn.state(['disabled'])
        self.call('join', code=self.code.get().strip())

    def leave(self):
        if messagebox.askyesno('FL Cowork', 'Quitter la session ?'):
            self.call('leave')

    def commit(self):
        self.call('publish', msg=self.commit_msg.get().strip())
        self.commit_msg.set('')

    def restore(self):
        sel = self.hist.selection()
        if not sel:
            messagebox.showinfo('FL Cowork', "Sélectionnez d'abord une version dans la liste.")
            return
        n = int(sel[0])
        if messagebox.askyesno('Restaurer', 'Revenir à la version %d chez tous les participants ?\n\n'
                                            "Une nouvelle version identique à celle-là sera créée ; l'historique est conservé." % n):
            self.call('restore', n=n)

    def force_send(self):
        if messagebox.askyesno('Imposer ma version',
                               "Envoyer le projet tel qu'il est chez vous, SANS fusion ?\n\n"
                               "Il remplacera la version partagée chez tous les participants. Leur travail "
                               "non envoyé sera copié dans leur dossier « Sauvegardes ».\n\n"
                               "À utiliser si vous vous êtes trompé de projet."):
            self.call('force_send')

    def force_recv(self):
        if messagebox.askyesno('Prendre leur version',
                               "Recharger la dernière version partagée, SANS fusion ?\n\n"
                               "Votre projet actuel sera remplacé. Une copie est conservée dans le dossier "
                               "« Sauvegardes » de la session."):
            self.call('force_recv')

    def send_chat(self):
        t = self.msg.get().strip()
        if t:
            self.call('chat', text=t)
            self.msg.set('')

    def gen_code(self):
        def got(res):
            if res.get('code'):
                self.gen_var.set(res['code'])
                self.gen_entry.pack(fill='x', pady=(4, 0))
        self.call('code', done=got, ip=self.ip.get())

    def copy(self, text):
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)

    def on_close(self):
        s = self.app.state().get('session')
        if s and not messagebox.askyesno('FL Cowork', 'Fermer FL Cowork ? Vous quitterez la session.'):
            return
        self.call('quit')
        self.after(600, self.destroy)

    # ------------------------------------------------------------- rafraichissement
    def tick(self):
        for item in list(self.pending):
            fut, done = item
            if fut.done():
                self.pending.remove(item)
                self.host_btn.state(['!disabled'])
                self.join_btn.state(['!disabled'])
                try:
                    res = fut.result() or {}
                    if done:
                        done(res)
                except Exception as e:
                    self.err.set(str(e) or e.__class__.__name__)
        if not self.thread.is_alive():
            self.destroy()
            return
        try:
            if self.app.loop is not None:
                self.render(self.app.state())
        except Exception as e:     # un rafraichissement rate ne doit jamais fermer la fenetre
            self.err.set('Affichage : %s' % e)
        self.after(500, self.tick)

    def render(self, S):
        if S['notice']:
            self.err.set(S['notice'])
        fl = S['fl']
        self.fl_lbl.configure(text='FL Studio : ' + ('connecté' + (' · ' + S['fl_title'] if S.get('fl_title') else '') if fl else 'non connecté'),
                              style='Ok.TLabel' if fl else 'Bad.TLabel')
        if self.focus_get() is not self.name_entry:
            if self.name.get() != S['name']:
                self.name.set(S['name'])
        sess = S['session']
        want = 'session' if sess else 'lobby'
        if want != self.mode:
            self.mode = want
            self.lobby.pack_forget()
            self.session.pack_forget()
            (self.session if sess else self.lobby).pack(fill='both', expand=True)
        if not sess:
            e = S['env']
            ok = {'script': e['script'], 'midi': e['midi'], 'fl': fl}
            for k, (lbl, txt) in self.chk.items():
                lbl.configure(text=('✔  ' if ok[k] else '○  ') + txt, style='Ok.TLabel' if ok[k] else 'TLabel')
            allok = all(ok.values())
            if allok:
                self.box.pack_forget()
            else:
                self.box.pack(fill='x', pady=(12, 0))
            if not (e['script'] and e['midi']):
                self.fix.pack(anchor='w', pady=(8, 0))
            else:
                self.fix.pack_forget()
            return
        # ----- session
        live = sess['live']
        self.st_title.configure(text='Prêt : Ctrl+S dans FL envoie votre version aux autres' if live else sess['why'])
        rev = sess['rev']
        sub = sess['project'] or ''
        if rev:
            sub += ' · version %d%s' % (rev['n'], ' (%s)' % rev['author'] if rev['author'] else '')
        self.st_sub.configure(text=sub)
        x = sess['xfer']
        if x and x['total']:
            self.bar.pack(fill='x', pady=(6, 0))
            self.bar.configure(value=100 * x['done'] / x['total'])
        else:
            self.bar.pack_forget()
        need = bool(rev) and (sess['local_n'] != rev['n'])
        manual = S.get('mode') == 'manual'
        self.btn_load.state(['!disabled' if need and not manual else 'disabled'])
        self.btn_send.configure(text='Envoyer' if manual else 'Envoyer et fusionner')
        if self.focus_get() is None or not isinstance(self.focus_get(), tk.Radiobutton):
            self.mode_var.set(S.get('mode', 'auto'))
        codes = sess['codes'] if sess['role'] == 'host' else {}
        host = sess['role'] == 'host'
        if host != self.invite_shown:
            self.invite_shown = host
            self.nb.tab(self.tab_invite, state='normal' if host else 'hidden')
        for key, (row, v) in self.code_vars.items():
            if codes.get(key):
                row.pack(fill='x', pady=(0, 6))
                v.set(codes[key])
            else:
                row.pack_forget()
        if host and not codes.get('wan'):
            self.ipbox.pack(fill='x')
        else:
            self.ipbox.pack_forget()
        # changements recus / locaux
        inc = sess.get('incoming')
        if inc:
            self.in_head.configure(text='%s · version %d%s%s' % (
                inc['author'], inc['n'], ' · « %s »' % inc['msg'] if inc['msg'] else '',
                ' · IMPOSÉE (remplace votre projet)' if inc['force'] else ''))
            lines = inc['lines'] or ['Analyse en cours…']
            if inc['force']:
                lines = lines + ['Cette version a été imposée : elle remplacera votre projet (copie dans Sauvegardes).']
            self.set_text(self.in_text, lines)
        show_in = bool(inc)
        show_out = bool(manual or sess['local_dirty'])
        if (show_in, show_out) != self.cards_state:
            self.cards_state = (show_in, show_out)
            self.in_card.pack_forget()
            self.out_card.pack_forget()
            if show_in:
                self.in_card.pack(fill='x', pady=(10, 0), before=self.adv_card)
            if show_out:
                self.out_card.pack(fill='x', pady=(10, 0), before=self.adv_card)
        if show_out:
            self.set_text(self.out_text, sess.get('local_lines') or ['Aucune modification locale depuis la dernière version.'])
        hist = sess.get('history') or []
        hs = tuple((h['n'], h.get('msg', '')) for h in hist)
        if hs != self.hist_sig:
            self.hist_sig = hs
            self.hist.delete(*self.hist.get_children())
            for h in reversed(hist):
                self.hist.insert('', 'end', iid=str(h['n']), text=str(h['n']),
                                 values=(h.get('author_name', ''), time.strftime('%d/%m %H:%M', time.localtime(h['time'])),
                                         (h.get('msg') or '') + (' [imposée]' if h.get('force') and not h.get('msg') else '')))
        sig = tuple((p['name'], p['me'], p['fl'], p['where'], p['play']) for p in sess['peers'])
        if sig != self.peer_sig:
            self.peer_sig = sig
            self.peers.delete(*self.peers.get_children())
            for p in sess['peers']:
                self.peers.insert('', 'end', text=p['name'] + (' (vous)' if p['me'] else ''),
                                  values=('ouvert' if p['fl'] else 'fermé', (p['where'] or '') + (' ▶' if p['play'] else '')))
        if self.focus_get() is None or not isinstance(self.focus_get(), tk.Checkbutton):
            self.autoload.set(bool(S['autoload']))
        chat = sess['chat']
        key = (len(chat), chat[-1]['time'] if chat else 0)
        if key != self.chat_n:
            self.chat_n = key
            self.chat.configure(state='normal')
            self.chat.delete('1.0', 'end')
            for m in chat:
                stamp = time.strftime('%H:%M ', time.localtime(m.get('time', time.time())))
                if m.get('sys'):
                    self.chat.insert('end', stamp + m['text'] + '\n', 'sys')
                else:
                    self.chat.insert('end', stamp)
                    self.chat.insert('end', m.get('name', '?') + ' ', 'who')
                    self.chat.insert('end', m['text'] + '\n')
            self.chat.configure(state='disabled')
            self.chat.see('end')


def run(app_factory):
    """Demarre l'application dans un fil et la fenetre dans le fil principal."""
    import threading
    holder = {}
    ready = threading.Event()

    def worker():
        app = app_factory()
        holder['app'] = app
        ready.set()
        try:
            asyncio.run(app.run(open_ui=False))
        finally:
            ready.set()
    t = threading.Thread(target=worker, daemon=True)
    t.start()
    ready.wait(10)
    app = holder['app']
    for _ in range(100):               # attend que la boucle soit prete
        if app.loop is not None or not t.is_alive():
            break
        time.sleep(0.05)
    if not t.is_alive():
        env.message_box('FL Cowork est déjà ouvert.', warn=False)
        return
    Gui(app, ready, t).mainloop()
