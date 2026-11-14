"""Editors for desktop-pet reminders and context-menu layout."""
from datetime import datetime
from time import time

from PySide6.QtCore import QDateTime, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox, QDateTimeEdit, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QKeySequenceEdit, QLineEdit,
    QListWidget, QListWidgetItem, QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)


def edit_hotkey(parent, sequence):
    dialog = QDialog(parent)
    dialog.setWindowTitle('设置全局显隐快捷键')
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel('请按住 Ctrl、Alt、Shift 或 Win，再按一个字母或数字。'))
    edit = QKeySequenceEdit(sequence)
    edit.setMaximumSequenceLength(1)
    layout.addWidget(edit)
    buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec():
        return edit.keySequence().toString(QKeySequence.PortableText)
    return None


def button_row(layout, buttons):
    row = QHBoxLayout()
    for label, callback in buttons:
        button = QPushButton(label)
        button.clicked.connect(callback)
        row.addWidget(button)
    layout.addLayout(row)


def edit_menu(parent, labels, hidden, groups=None):
    dialog = QDialog(parent)
    dialog.setWindowTitle('配置菜单')
    dialog.resize(380, 480)
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel('勾选要显示的条目，拖动调整顺序。选中条目后可设置子菜单。'))
    items = QListWidget()
    items.setDragDropMode(QListWidget.DragDropMode.InternalMove)
    layout.addWidget(items)
    for label in labels:
        item = QListWidgetItem(label, items)
        item.setCheckState(Qt.Unchecked if label in hidden else Qt.Checked)
        item.setData(Qt.UserRole, (groups or {}).get(label, ''))

    group = QLineEdit()
    group.setMaxLength(30)
    group.setPlaceholderText('子菜单名称，留空放在顶层')
    layout.addWidget(group)
    items.currentItemChanged.connect(lambda current, _: group.setText(current.data(Qt.UserRole) if current else ''))

    def set_group(text):
        item = items.currentItem()
        if item:
            item.setData(Qt.UserRole, text.strip())

    group.textEdited.connect(set_group)
    items.setCurrentRow(0)
    preview = QLabel()
    preview.setWordWrap(True)
    preview.setTextFormat(Qt.PlainText)

    def update_preview():
        visible = {}
        for index in range(items.count()):
            item = items.item(index)
            if item.checkState() == Qt.Checked:
                name = item.data(Qt.UserRole)
                if name:
                    visible.setdefault(('group', name), []).append(item.text())
                else:
                    visible[('item', item.text())] = []
        labels = [f'{name}（{"、".join(children)}）' if children else name
                  for (_, name), children in visible.items()]
        preview.setText('菜单顺序：' + (' → '.join(labels) or '无自定义条目'))

    items.itemChanged.connect(update_preview)
    items.model().rowsMoved.connect(update_preview)
    items.model().rowsInserted.connect(update_preview)
    items.model().rowsRemoved.connect(update_preview)
    update_preview()
    layout.addWidget(preview)
    buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if not dialog.exec():
        return None
    order = [items.item(index) for index in range(items.count())]
    return ([item.text() for item in order],
            [item.text() for item in order if item.checkState() == Qt.Unchecked],
            {item.text(): item.data(Qt.UserRole) for item in order if item.data(Qt.UserRole)})


def edit_settings(pet):
    dialog = QDialog(pet)
    dialog.setWindowTitle('桌宠设置')
    form = QFormLayout(dialog)
    numbers = {}
    for key, label, current, minimum, maximum in (
        ('opacity', '不透明度（%）', pet.opacity, 20, 100),
        ('speed', '播放速率（%）', pet.speed, 25, 300),
        ('interval', '自动互动间隔（秒）', pet.interval, 5, 3600),
        ('bubble_font', '气泡字号（像素）', pet.bubble_font, 10, 24),
    ):
        field = QSpinBox()
        field.setRange(minimum, maximum)
        field.setValue(current)
        form.addRow(label, field)
        numbers[key] = field
    switches = {}
    for key, label, checked in (
        ('auto', '自动互动', pet.auto_enabled),
        ('locked', '锁定位置', pet.locked),
        ('click_sound', '点击音效', pet.settings.value('click_sound', False, type=bool)),
        ('self_talk', '随机自言自语', pet.settings.value('self_talk', False, type=bool)),
        ('edge_probe', '边缘探头', pet.settings.value('edge_probe', False, type=bool)),
    ):
        field = QCheckBox()
        field.setChecked(checked)
        form.addRow(label, field)
        switches[key] = field
    buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)
    if not dialog.exec():
        return None
    return ({key: field.value() for key, field in numbers.items()},
            {key: field.isChecked() for key, field in switches.items()})


class TodoDialog(QDialog):
    def __init__(self, pet):
        super().__init__(pet)
        self.pet = pet
        self.setWindowTitle('待办提醒')
        self.resize(520, 360)
        layout = QVBoxLayout(self)
        self.items = QListWidget()
        layout.addWidget(self.items)
        button_row(layout, [('添加', self.add), ('编辑', self.edit), ('删除', self.remove), ('关闭', self.accept)])
        self.items.itemDoubleClicked.connect(lambda item: self.edit())
        self.refresh()

    def refresh(self):
        selected = self.selected()
        self.items.clear()
        self.rows = sorted(self.pet.todos, key=lambda todo: (bool(todo.get('archived')), todo['due']))
        for todo in self.rows:
            due = datetime.fromtimestamp(todo['due']).strftime('%Y-%m-%d %H:%M')
            status = '已归档' if todo.get('archived') else '待提醒'
            self.items.addItem(f'{status}  {due}  {todo["text"]}')
        if selected is not None:
            for index, todo in enumerate(self.rows):
                if todo is selected:
                    self.items.setCurrentRow(index)
                    break

    def selected(self):
        row = self.items.currentRow()
        return self.rows[row] if row >= 0 else None

    def add(self):
        self.edit_item(None)

    def edit(self):
        todo = self.selected()
        if todo is not None:
            self.edit_item(todo)

    def remove(self):
        todo = self.selected()
        if todo is not None:
            self.pet.todos[:] = [item for item in self.pet.todos if item is not todo]
            self.pet.save_todos()

    def edit_item(self, todo):
        dialog = QDialog(self)
        dialog.setWindowTitle('设置提醒')
        form = QFormLayout(dialog)
        text = QLineEdit(todo['text'] if todo else '')
        text.setMaxLength(100)
        due = int(todo['due']) if todo and not todo.get('archived') else int(time()) + 300
        when = QDateTimeEdit(QDateTime.fromSecsSinceEpoch(due))
        when.setDisplayFormat('yyyy-MM-dd HH:mm')
        when.setCalendarPopup(True)
        lead = QSpinBox()
        lead.setRange(0, 1440)
        lead.setValue(todo.get('lead', 0) if todo else 5)
        lead.setSpecialValueText('关闭')
        form.addRow('事项', text)
        form.addRow('到期时间', when)
        form.addRow('提前提醒（分钟）', lead)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        save = buttons.button(QDialogButtonBox.Save)
        text.textChanged.connect(lambda value: save.setEnabled(bool(value.strip())))
        save.setEnabled(bool(text.text().strip()))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if not dialog.exec():
            return
        updated = {'text': text.text().strip(), 'due': when.dateTime().toSecsSinceEpoch(), 'lead': lead.value()}
        if todo is None:
            self.pet.todos.append(updated)
        else:
            if updated['due'] == todo['due'] and updated['lead'] == todo.get('lead', 0) and todo.get('warned'):
                updated['warned'] = True
            todo.clear()
            todo.update(updated)
        self.pet.save_todos()
