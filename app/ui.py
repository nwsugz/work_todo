"""보드 화면. TODO / TBD 두 칸, 드래그로 옮기면 그 자리에 고정됩니다."""

from __future__ import annotations

import sys
from datetime import date

from PySide6.QtCore import QDate, QPointF, QRect, QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from . import storage
from .models import COLUMNS, TBD, TODO, Task
from .rules import apply_rules, classify

CANVAS = "#1C1F26"
SURFACE = "#262A33"
BORDER = "#343A45"
TEXT = "#E6E8EC"
MUTED = "#98A0AB"
AMBER = "#E2B341"
SLATE = "#7C8593"
PIN = "#7FB2E5"
DONE_GREEN = "#3FBF6F"
URGENT_OVERDUE = "#E2574C"
URGENT_OVERDUE_BG = "#3B2229"
URGENT_SOON = "#E2954A"
URGENT_SOON_BG = "#3A2C1E"
URGENT_DAYS = 3  # 마감일까지 이 안이면 '임박'으로 표시

ROLE_TASK_ID = Qt.ItemDataRole.UserRole
ROLE_CARD = Qt.ItemDataRole.UserRole + 1

COLUMN_LABEL = {TODO: "TODO", TBD: "TBD"}
COLUMN_ACCENT = {TODO: AMBER, TBD: SLATE}

CHECK_SIZE = 16
CHECK_LEFT_PAD = 10


def checkbox_rect(card_rect: QRect) -> QRect:
    """카드의(패딩 적용된) 사각형을 받아 체크박스 위치를 돌려줍니다."""
    y = card_rect.top() + (card_rect.height() - CHECK_SIZE) // 2
    return QRect(card_rect.left() + CHECK_LEFT_PAD, y, CHECK_SIZE, CHECK_SIZE)


def ui_font(size: int = 10, bold: bool = False) -> QFont:
    font = QFont("Malgun Gothic" if sys.platform == "win32" else "Noto Sans CJK KR", size)
    font.setBold(bold)
    return font


def due_caption(task: Task, today: date | None = None) -> str:
    if not task.due:
        return "마감일 없음"
    today = today or date.today()
    try:
        due = date.fromisoformat(task.due)
    except ValueError:
        return "마감일 없음"
    days = (due - today).days
    if days < 0:
        return f"{task.due} · {-days}일 지남"
    if days == 0:
        return f"{task.due} · 오늘"
    return f"{task.due} · {days}일 남음"


def task_urgency(task: Task, today: date | None = None) -> str | None:
    """마감일 기준 긴급도. 완료된 업무나 마감일이 없는 업무는 None."""
    if task.done or not task.due:
        return None
    today = today or date.today()
    try:
        due = date.fromisoformat(task.due)
    except ValueError:
        return None
    days = (due - today).days
    if days < 0:
        return "overdue"
    if days <= URGENT_DAYS:
        return "soon"
    return None


class CardDelegate(QStyledItemDelegate):
    """제목 한 줄, 그 아래 상태 한 줄. 고정된 업무는 왼쪽에 파란 막대가 붙습니다."""

    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width(), 62)

    def paint(self, painter: QPainter, option, index) -> None:
        card = index.data(ROLE_CARD) or {}
        rect = option.rect.adjusted(4, 3, -4, -3)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        urgency = card.get("urgency")
        if urgency == "overdue":
            background, border_color, border_width = QColor(URGENT_OVERDUE_BG), QColor(URGENT_OVERDUE), 1.6
        elif urgency == "soon":
            background, border_color, border_width = QColor(URGENT_SOON_BG), QColor(URGENT_SOON), 1.6
        else:
            background = QColor("#2F3541") if selected else QColor(SURFACE)
            border_color, border_width = QColor(BORDER), 1.0
        if selected and urgency:
            background = background.lighter(115)
        painter.setPen(QPen(border_color, border_width))
        painter.setBrush(background)
        painter.drawRoundedRect(rect, 6, 6)

        if card.get("pinned"):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(PIN))
            painter.drawRoundedRect(QRect(rect.left() + 1, rect.top() + 8, 3, rect.height() - 16), 2, 2)

        box = checkbox_rect(rect)
        checked = bool(card.get("checked")) or bool(card.get("done"))
        painter.setPen(QPen(QColor(DONE_GREEN if checked else BORDER), 1.4))
        painter.setBrush(QColor(DONE_GREEN) if checked else Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(box, 4, 4)
        if checked:
            mark = QPen(QColor("#12261A"), 2)
            mark.setCapStyle(Qt.PenCapStyle.RoundCap)
            mark.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(mark)
            painter.drawLine(QPointF(box.left() + 3, box.top() + 8.5), QPointF(box.left() + 6.5, box.bottom() - 3))
            painter.drawLine(QPointF(box.left() + 6.5, box.bottom() - 3), QPointF(box.right() - 2.5, box.top() + 3))

        text_left = box.right() + 10
        text_width = rect.right() - text_left - 6

        painter.setFont(ui_font(10, bold=True))
        title_color = QColor(MUTED) if checked else QColor(TEXT)
        painter.setPen(title_color)
        title = card.get("title", "")
        metrics = painter.fontMetrics()
        elided = metrics.elidedText(title, Qt.TextElideMode.ElideRight, text_width)
        painter.drawText(QRect(text_left, rect.top() + 10, text_width, 18), Qt.AlignmentFlag.AlignVCenter, elided)
        if checked:
            width = min(metrics.horizontalAdvance(elided), text_width)
            y = rect.top() + 19
            painter.drawLine(text_left, y, text_left + width, y)

        painter.setFont(ui_font(8))
        painter.setPen(QColor(MUTED))
        meta = painter.fontMetrics().elidedText(card.get("meta", ""), Qt.TextElideMode.ElideRight, text_width)
        painter.drawText(QRect(text_left, rect.top() + 32, text_width, 16), Qt.AlignmentFlag.AlignVCenter, meta)
        painter.restore()


class ColumnList(QListWidget):
    """드롭을 직접 처리합니다. 목록은 컨트롤러가 다시 그립니다."""

    taskDropped = Signal(str, str, int, bool)  # 업무 id, 대상 칸, 위치, 칸이 바뀌었는지
    taskCheckToggled = Signal(str)  # 업무 id — 체크 표시만 바꿈 (자리 유지)
    taskCompleteRequested = Signal(str)  # 업무 id — 완료 처리(칸 아래로/숨김)

    def __init__(self, column: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.column = column
        self.setItemDelegate(CardDelegate(self))
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setSpacing(0)
        self.setUniformItemSizes(True)
        self.setMouseTracking(True)

    def _item_at_checkbox(self, pos) -> QListWidgetItem | None:
        index = self.indexAt(pos)
        if not index.isValid():
            return None
        item = self.itemFromIndex(index)
        rect = self.visualItemRect(item).adjusted(4, 3, -4, -3)
        return item if checkbox_rect(rect).contains(pos) else None

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            item = self._item_at_checkbox(event.position().toPoint())
            if item is not None:
                self.taskCheckToggled.emit(item.data(ROLE_TASK_ID))
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        item = self._item_at_checkbox(event.position().toPoint())
        self.setCursor(Qt.CursorShape.PointingHandCursor if item is not None else Qt.CursorShape.ArrowCursor)
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            # 오른쪽 버튼으로 누르고 살짝 움직였을 때 드래그로 오인하지 않게 막습니다.
            return
        super().mouseMoveEvent(event)

    def startDrag(self, supportedActions) -> None:
        if QApplication.mouseButtons() != Qt.MouseButton.LeftButton:
            return
        super().startDrag(supportedActions)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            item = self.currentItem()
            if item is not None:
                self.taskCompleteRequested.emit(item.data(ROLE_TASK_ID))
                event.accept()
                return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event) -> None:
        if isinstance(event.source(), ColumnList):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if isinstance(event.source(), ColumnList):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        source = event.source()
        if not isinstance(source, ColumnList):
            event.ignore()
            return
        items = source.selectedItems()
        if not items:
            event.ignore()
            return
        item = items[0]
        task_id = item.data(ROLE_TASK_ID)

        row = self.indexAt(event.position().toPoint()).row()
        if row < 0:
            row = self.count()
        elif self.dropIndicatorPosition() == QAbstractItemView.DropIndicatorPosition.BelowItem:
            row += 1

        moved_across = source is not self
        if not moved_across:
            current_row = self.row(item)
            if row > current_row:
                row -= 1

        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()
        self.taskDropped.emit(task_id, self.column, row, moved_across)


class TaskDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        task: Task | None = None,
        categories: list[str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("업무 편집" if task else "새 업무")
        self.setMinimumWidth(400)
        categories = categories or []

        self.title_edit = QLineEdit(task.title if task else "")
        self.title_edit.setPlaceholderText("무엇을 해야 하나요?")

        self.category_combo = QComboBox()
        self.category_combo.addItem("(없음)", None)
        for name in categories:
            self.category_combo.addItem(name, name)
        if task and task.category in categories:
            self.category_combo.setCurrentIndex(categories.index(task.category) + 1)

        self.no_due = QCheckBox("마감일 없음")
        self.due_edit = QDateEdit()
        self.due_edit.setCalendarPopup(True)
        self.due_edit.setDisplayFormat("yyyy-MM-dd")
        if task and task.due:
            self.due_edit.setDate(QDate.fromString(task.due, "yyyy-MM-dd"))
        else:
            self.due_edit.setDate(QDate.currentDate())
            self.no_due.setChecked(True)
        self.no_due.toggled.connect(lambda checked: self.due_edit.setEnabled(not checked))
        self.due_edit.setEnabled(not self.no_due.isChecked())

        due_row = QHBoxLayout()
        due_row.addWidget(self.due_edit, 1)
        due_row.addWidget(self.no_due)

        self.tags_edit = QLineEdit(", ".join(task.tags) if task else "")
        self.tags_edit.setPlaceholderText("쉼표로 구분 (예: 대기, 보고)")

        self.note_edit = QPlainTextEdit(task.note if task else "")
        self.note_edit.setPlaceholderText("메모. 규칙의 단어 조건은 메모도 함께 봅니다.")
        self.note_edit.setFixedHeight(90)

        form = QFormLayout()
        form.addRow("제목", self.title_edit)
        form.addRow("카테고리", self.category_combo)
        form.addRow("마감일", due_row)
        form.addRow("태그", self.tags_edit)
        form.addRow("메모", self.note_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("저장")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def accept(self) -> None:
        if not self.title_edit.text().strip():
            QMessageBox.information(self, "제목이 비었습니다", "제목을 입력해 주세요.")
            self.title_edit.setFocus()
            return
        super().accept()

    def values(self) -> dict:
        tags = [t.strip() for t in self.tags_edit.text().split(",") if t.strip()]
        return {
            "title": self.title_edit.text().strip(),
            "category": self.category_combo.currentData(),
            "due": None if self.no_due.isChecked() else self.due_edit.date().toString("yyyy-MM-dd"),
            "tags": tags,
            "note": self.note_edit.toPlainText().strip(),
        }


class SettingsDialog(QDialog):
    """카테고리 우선순위(위쪽일수록 우선) 설정. 목록을 드래그해서 순서를 바꿉니다."""

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.window = window
        self.setWindowTitle("설정")
        self.setMinimumWidth(360)

        category_label = QLabel("카테고리 우선순위")
        self.category_list = QListWidget()
        self.category_list.addItems(self.window.settings.get("categories", []))
        self.category_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.category_list.model().rowsMoved.connect(lambda *_: self._sync())

        add_button = QPushButton("추가")
        add_button.clicked.connect(self._add_category)
        remove_button = QPushButton("삭제")
        remove_button.clicked.connect(self._remove_category)

        category_buttons = QHBoxLayout()
        category_buttons.addWidget(add_button)
        category_buttons.addWidget(remove_button)
        category_buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(category_label)
        layout.addWidget(self.category_list)
        layout.addLayout(category_buttons)

    def _category_names(self) -> list[str]:
        return [self.category_list.item(i).text() for i in range(self.category_list.count())]

    def _add_category(self) -> None:
        name, ok = QInputDialog.getText(self, "카테고리 추가", "이름")
        name = name.strip()
        if not ok or not name or name in self._category_names():
            return
        self.category_list.addItem(name)
        self._sync()

    def _remove_category(self) -> None:
        row = self.category_list.currentRow()
        if row >= 0:
            self.category_list.takeItem(row)
            self._sync()

    def _sync(self) -> None:
        self.window.settings["categories"] = self._category_names()
        storage.save_settings(self.window.settings)
        self.window.reapply_rules()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("TODO / TBD 보드")
        self.resize(880, 620)

        self.tasks: list[Task] = storage.load_tasks()
        self.rules, _ = storage.load_rules()
        self.settings: dict = storage.load_settings()
        self.show_done = False

        self.lists: dict[str, ColumnList] = {}
        self.counters: dict[str, QLabel] = {}

        self._build_ui()
        self._restore_settings()
        apply_rules(self.tasks, self.rules)
        self.render()

    # 화면 구성 -------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(16, 14, 16, 10)
        outer.setSpacing(12)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        add_button = QPushButton("새 업무")
        add_button.setObjectName("primary")
        add_button.clicked.connect(self.add_task)
        settings_button = QPushButton("⚙ 설정")
        settings_button.clicked.connect(self.open_settings)
        self.done_toggle = QPushButton("완료 항목 보기")
        self.done_toggle.setCheckable(True)
        self.done_toggle.toggled.connect(self.toggle_done)
        self.pin_toggle = QPushButton("📌 항상 위")
        self.pin_toggle.setCheckable(True)
        self.pin_toggle.setToolTip("다른 창을 띄워도 이 창이 뒤로 가지 않습니다. (Ctrl+T)")
        self.pin_toggle.toggled.connect(self.toggle_always_on_top)
        toolbar.addWidget(add_button)
        toolbar.addWidget(settings_button)
        toolbar.addStretch(1)
        toolbar.addWidget(self.done_toggle)
        toolbar.addWidget(self.pin_toggle)
        outer.addLayout(toolbar)

        board = QHBoxLayout()
        board.setSpacing(14)
        for column in COLUMNS:
            board.addWidget(self._build_column(column), 1)
        outer.addLayout(board, 1)

        self.setCentralWidget(central)

        new_action = QAction(self)
        new_action.setShortcut(QKeySequence.StandardKey.New)
        new_action.triggered.connect(self.add_task)
        refresh_action = QAction(self)
        refresh_action.setShortcut(QKeySequence("F5"))
        refresh_action.triggered.connect(self.reapply_rules)
        pin_action = QAction(self)
        pin_action.setShortcut(QKeySequence("Ctrl+T"))
        pin_action.triggered.connect(self.pin_toggle.toggle)
        self.addAction(new_action)
        self.addAction(refresh_action)
        self.addAction(pin_action)

        self.setStyleSheet(self._stylesheet())

    def _restore_settings(self) -> None:
        with QSignalBlocker(self.done_toggle):
            self.done_toggle.setChecked(bool(self.settings.get("show_done", False)))
        self.show_done = self.done_toggle.isChecked()

        always_on_top = bool(self.settings.get("always_on_top", False))
        with QSignalBlocker(self.pin_toggle):
            self.pin_toggle.setChecked(always_on_top)
        if always_on_top:
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        geo = self.settings.get("geometry")
        if isinstance(geo, dict) and all(isinstance(geo.get(k), int) for k in ("x", "y", "w", "h")):
            self.setGeometry(geo["x"], geo["y"], geo["w"], geo["h"])

    def _build_column(self, column: str) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header = QHBoxLayout()
        name = QLabel(COLUMN_LABEL[column])
        name.setFont(ui_font(12, bold=True))
        name.setStyleSheet(f"color: {COLUMN_ACCENT[column]};")
        count = QLabel("0")
        count.setObjectName("count")
        header.addWidget(name)
        header.addWidget(count)
        header.addStretch(1)
        layout.addLayout(header)

        listing = ColumnList(column)
        listing.taskDropped.connect(self.on_task_dropped)
        listing.taskCheckToggled.connect(self.on_task_check_toggled)
        listing.taskCompleteRequested.connect(self.on_task_complete_requested)
        listing.customContextMenuRequested.connect(
            lambda pos, c=column: self.show_context_menu(c, pos)
        )
        listing.itemDoubleClicked.connect(self.edit_selected)
        layout.addWidget(listing, 1)

        self.lists[column] = listing
        self.counters[column] = count
        return wrapper

    def _stylesheet(self) -> str:
        return f"""
        QMainWindow, QWidget {{ background: {CANVAS}; color: {TEXT}; }}
        QLabel {{ color: {TEXT}; }}
        QLabel#count {{ color: {MUTED}; font-size: 12px; }}
        QPushButton {{
            background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 5px;
            padding: 6px 12px; color: {TEXT};
        }}
        QPushButton:hover {{ background: #2F3541; }}
        QPushButton:checked {{ border-color: {PIN}; color: {PIN}; }}
        QPushButton#primary {{ background: {AMBER}; border-color: {AMBER}; color: #1C1F26; font-weight: bold; }}
        QPushButton#primary:hover {{ background: #EFC456; }}
        QListWidget {{
            background: #1F232B; border: 1px solid {BORDER}; border-radius: 8px; padding: 4px;
        }}
        QListWidget::item {{ border: none; }}
        QLineEdit, QPlainTextEdit, QDateEdit {{
            background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 4px;
            padding: 5px; color: {TEXT};
        }}
        QDialog {{ background: {CANVAS}; }}
        """

    # 그리기 ----------------------------------------------------------------
    def category_rank(self, task: Task) -> int:
        """설정에서 정한 카테고리 우선순위. 목록 위쪽(인덱스 0)이 가장 높은 우선순위입니다.
        카테고리가 없거나 목록에 없는 값이면 가장 낮은 우선순위로 취급합니다."""
        categories = self.settings.get("categories", [])
        if task.category and task.category in categories:
            return categories.index(task.category)
        return len(categories)

    def visible_tasks(self, column: str) -> list[Task]:
        items = [t for t in self.tasks if t.column == column and (self.show_done or not t.done)]
        return sorted(items, key=lambda t: (t.done, self.category_rank(t), t.order))

    def render(self) -> None:
        for column, listing in self.lists.items():
            selected_id = None
            current = listing.currentItem()
            if current:
                selected_id = current.data(ROLE_TASK_ID)
            listing.clear()
            tasks = self.visible_tasks(column)
            for task in tasks:
                item = QListWidgetItem()
                item.setData(ROLE_TASK_ID, task.id)
                item.setData(ROLE_CARD, self._card(task))
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDragEnabled)
                listing.addItem(item)
                if task.id == selected_id:
                    listing.setCurrentItem(item)
            pinned = sum(1 for t in tasks if t.pinned)
            label = str(len(tasks)) + (f" · 고정 {pinned}" if pinned else "")
            self.counters[column].setText(label)

    def _card(self, task: Task) -> dict:
        parts = []
        if task.category:
            parts.append(f"[{task.category}]")
        parts.append(due_caption(task))
        if task.tags:
            parts.append(" ".join(f"#{t}" for t in task.tags))
        parts.append("직접 옮김 · 규칙 제외" if task.pinned else (task.matched_rule or "규칙 미적용"))
        return {
            "title": task.title,
            "meta": "  ·  ".join(parts),
            "pinned": task.pinned,
            "checked": task.checked,
            "done": task.done,
            "urgency": task_urgency(task),
        }

    # 동작 ------------------------------------------------------------------
    def find(self, task_id: str) -> Task | None:
        return next((t for t in self.tasks if t.id == task_id), None)

    def reorder(self, column: str, task_id: str, row: int) -> None:
        ids = [t.id for t in self.visible_tasks(column) if t.id != task_id]
        row = max(0, min(row, len(ids)))
        ids.insert(row, task_id)
        position = {task_id: index for index, task_id in enumerate(ids)}
        for task in self.tasks:
            if task.id in position:
                task.order = position[task.id]

    def on_task_dropped(self, task_id: str, column: str, row: int, moved_across: bool) -> None:
        task = self.find(task_id)
        if task is None:
            return
        if moved_across:
            task.column = column
            task.pinned = True
        self.reorder(column, task_id, row)
        self.persist()
        self.render()

    def add_task(self) -> None:
        dialog = TaskDialog(self, categories=self.settings.get("categories", []))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        task = Task(**values)
        task.column, task.matched_rule = classify(task, self.rules)
        task.order = len(self.visible_tasks(task.column))
        self.tasks.append(task)
        self.persist()
        self.render()

    def current_task(self, column: str) -> Task | None:
        item = self.lists[column].currentItem()
        return self.find(item.data(ROLE_TASK_ID)) if item else None

    def edit_selected(self, item: QListWidgetItem) -> None:
        task = self.find(item.data(ROLE_TASK_ID))
        if task:
            self.edit_task(task)

    def edit_task(self, task: Task) -> None:
        dialog = TaskDialog(self, task, categories=self.settings.get("categories", []))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        for key, value in dialog.values().items():
            setattr(task, key, value)
        if not task.pinned:
            task.column, task.matched_rule = classify(task, self.rules)
        self.persist()
        self.render()

    def unpin(self, task: Task) -> None:
        task.pinned = False
        task.column, task.matched_rule = classify(task, self.rules)
        self.persist()
        self.render()

    def toggle_done(self, checked: bool) -> None:
        self.show_done = checked
        self.render()

    def toggle_always_on_top(self, checked: bool) -> None:
        was_visible = self.isVisible()
        flags = self.windowFlags()
        if checked:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        if was_visible:
            self.show()
        self.settings["always_on_top"] = checked
        storage.save_settings(self.settings)

    def delete_task(self, task: Task) -> None:
        answer = QMessageBox.question(self, "삭제", f"'{task.title}'을(를) 지울까요?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.tasks = [t for t in self.tasks if t.id != task.id]
        self.persist()
        self.render()

    def show_context_menu(self, column: str, pos) -> None:
        task = self.current_task(column)
        listing = self.lists[column]
        item = listing.itemAt(pos)
        if item:
            listing.setCurrentItem(item)
            task = self.find(item.data(ROLE_TASK_ID))
        if task is None:
            return
        menu = QMenu(self)
        menu.addAction("편집", lambda: self.edit_task(task))
        menu.addAction("완료 취소" if task.done else "완료 처리", lambda: self.set_done(task, not task.done))
        if task.pinned:
            menu.addAction("고정 풀고 규칙에 맡기기", lambda: self.unpin(task))
        else:
            menu.addAction("이 자리에 고정", lambda: self.pin(task))
        menu.addSeparator()
        menu.addAction("삭제", lambda: self.delete_task(task))
        menu.exec(listing.mapToGlobal(pos))

    def pin(self, task: Task) -> None:
        task.pinned = True
        self.persist()
        self.render()

    def set_done(self, task: Task, done: bool) -> None:
        task.done = done
        self.persist()
        self.render()

    def set_checked(self, task: Task, checked: bool) -> None:
        task.checked = checked
        self.persist()
        self.render()

    def on_task_check_toggled(self, task_id: str) -> None:
        task = self.find(task_id)
        if task is None:
            return
        self.set_checked(task, not task.checked)

    def on_task_complete_requested(self, task_id: str) -> None:
        task = self.find(task_id)
        if task is None or task.done:
            return
        self.set_done(task, True)

    def reapply_rules(self) -> None:
        self.rules, _ = storage.load_rules()
        apply_rules(self.tasks, self.rules)
        self.persist()
        self.render()

    def open_settings(self) -> None:
        dialog = SettingsDialog(self)
        dialog.exec()
        self.render()

    def persist(self) -> None:
        storage.save_tasks(self.tasks)

    def closeEvent(self, event) -> None:
        self.persist()
        geo = self.geometry()
        self.settings.update({
            "show_done": self.show_done,
            "always_on_top": bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint),
            "geometry": {"x": geo.x(), "y": geo.y(), "w": geo.width(), "h": geo.height()},
        })
        storage.save_settings(self.settings)
        super().closeEvent(event)


def run() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("TodoTBD")
    app.setFont(ui_font(10))
    window = MainWindow()
    window.show()
    return app.exec()
