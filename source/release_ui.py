"""Local launcher for the file-based editor and verified export."""
import datetime
import os
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser


def launch():
    from guanchuang import VERSION, import_gui, source_info, verify_export
    window = tk.Tk()
    window.title('观窗 · CK3 GUI 外观编辑')
    window.geometry('760x650')
    window.minsize(600, 480)
    panel = ttk.Frame(window,padding=22)
    panel.pack(fill='both',expand=True)
    panel.columnconfigure(1,weight=1)
    ttk.Label(panel,text='观窗',font=('Microsoft YaHei UI',23,'bold')).grid(row=0,column=0,columnspan=3,sticky='w')
    ttk.Label(panel,text=f'{VERSION}   ·   CK3 GUI 外观编辑').grid(row=1,column=0,columnspan=3,sticky='w',pady=(0,18))
    filename=tk.StringVar()
    choice=tk.StringVar()
    game=tk.StringVar()
    work=tk.StringVar(value=str(Path.home()/'Documents/观窗工作区'))
    css=tk.StringVar()
    clicks=tk.StringVar()
    viewport=tk.StringVar(value='1760x990')
    status=tk.StringVar(value='选择 CK3 GUI 查看整窗布局，或选择本地网页生成原生外观候选。')
    last={'package':None,'visual':None}
    def choose_file():
        selected=filedialog.askopenfilename(title='选择窗口来源',filetypes=[('GUI 或网页','*.gui *.html *.htm'),('CK3 GUI','*.gui'),('网页','*.html *.htm')])
        if not selected:
            return
        filename.set(selected)
        if Path(selected).suffix.lower() in ('.html','.htm'):
            selector.configure(state='normal',values=())
            choice.set('gc_layout')
            status.set('输入新窗口名；可指定网页窗口的 CSS 选择器及要取样的状态。')
            return
        selector.configure(state='readonly')
        try:
            _,_,_,roots=source_info(selected)
            names=[n.value('name') for n in roots]
            selector['values']=names
            choice.set(names[0] if names else '')
            status.set(f'找到 {len(names)} 个具名窗口。' if names else '这个文件没有可导入的具名窗口，共享类型定义可按源码查看。')
        except (OSError,ValueError) as error:
            choice.set('');selector['values']=()
            status.set(str(error))
    def folder(var,title):
        selected=filedialog.askdirectory(title=title)
        if selected:var.set(selected)
    def row(index,label,var,button,action):
        ttk.Label(panel,text=label).grid(row=index,column=0,sticky='w',padx=(0,9),pady=5)
        ttk.Entry(panel,textvariable=var,state='readonly').grid(row=index,column=1,sticky='ew')
        ttk.Button(panel,text=button,command=action).grid(row=index,column=2,padx=(7,0))
    row(2,'GUI 或网页',filename,'选择文件',choose_file)
    ttk.Label(panel,text='编辑窗口').grid(row=3,column=0,sticky='w',pady=5)
    selector=ttk.Combobox(panel,textvariable=choice,state='readonly')
    selector.grid(row=3,column=1,sticky='ew')
    row(4,'工作目录',work,'选择目录',lambda:folder(work,'选择工作目录'))
    row(5,'游戏资源（可选）',game,'选择目录',lambda:folder(game,'选择 CK3 的 game 目录'))
    def new_path(tag):
        return Path(work.get())/(tag+'-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    def open_editor():
        try:
            dest=new_path('编辑')
            src=filename.get()
            html_verdict=None
            if Path(src).suffix.lower() in ('.html','.htm'):
                from editing.html_layout import convert_html
                stage=new_path('网页转GUI')
                status.set('正在测量网页并生成游戏贴图…')
                window.update_idletasks()
                size=tuple(map(int,viewport.get().lower().split('x')))
                result=convert_html(src,stage,choice.get(),css.get().strip() or None,
                                    [s.strip() for s in clicks.get().split(';') if s.strip()],size,game.get() or None)
                html_verdict=result.get('visual_status')
                src=stage/result['gui']
                last['visual']=src.parent.parent
                show_output.configure(state='normal')
            result=import_gui(src,dest,choice.get(),game.get() or None)
            last['package']=dest
            webbrowser.open(Path(result['editor']).as_uri())
            state='需看复核项' if 'REVIEW_REQUIRED' in (html_verdict,result.get('visual_status')) else '已通过固定布局检查'
            status.set(f'{state}。可编辑控件 {len(result["targets"])} 个。工作目录 {dest}')
        except (OSError, ValueError, TypeError, KeyError) as error:
            messagebox.showerror('无法导入',str(error),parent=window)
    for rownum,title,var in [(6,'网页窗口选择器（可选）',css),(7,'取样前点击（用 ; 分隔）',clicks),(8,'网页画布宽×高',viewport)]:
        ttk.Label(panel,text=title).grid(row=rownum,column=0,sticky='w',pady=4)
        ttk.Entry(panel,textvariable=var).grid(row=rownum,column=1,sticky='ew')
    ttk.Button(panel,text='转换并打开整窗编辑页',command=open_editor).grid(row=9,column=0,columnspan=3,sticky='ew',pady=(13,8))
    ttk.Separator(panel).grid(row=10,column=0,columnspan=3,sticky='ew',pady=7)
    ttk.Label(panel,text='在编辑页下载完整 GUI 和编辑请求，再校验两个下载文件。',wraplength=560).grid(row=11,column=0,columnspan=3,sticky='w',pady=5)
    def verify():
        package=last['package'] or filedialog.askdirectory(title='选择包含 manifest.json 的编辑工作区')
        if not package:return
        request=filedialog.askopenfilename(title='选择下载的编辑请求 JSON',filetypes=[('JSON','*.json')])
        if not request:return
        export=filedialog.askopenfilename(title='选择同次下载的 GUI',filetypes=[('CK3 GUI','*.gui')])
        if not export:return
        try:
            dest=new_path('已校验')
            result=verify_export(package,request,export,dest)
            status.set(f'已重读 {len(result["patches"])} 处差异。输出目录 {dest}')
            messagebox.showinfo('导出校验',f'已生成完整 GUI 和最小差分。布局状态 {result.get("visual_status", "UNKNOWN")}，详见 visual-audit.json。\n{dest}',parent=window)
            os.startfile(dest)
        except (OSError,ValueError,TypeError,KeyError) as error:
            messagebox.showerror('校验未通过',str(error),parent=window)
    ttk.Button(panel,text='校验导出并生成最小差分',command=verify).grid(row=12,column=0,columnspan=3,sticky='ew',pady=7)
    ttk.Label(panel,textvariable=status,wraplength=560,justify='left').grid(row=13,column=0,columnspan=3,sticky='w',pady=9)
    show_output=ttk.Button(panel,text='打开最近生成的原生布局文件夹',state='disabled',command=lambda:os.startfile(last['visual']))
    show_output.grid(row=14,column=0,columnspan=3,sticky='ew',pady=5)
    window.mainloop()
