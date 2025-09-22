import math
from typing import Callable

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtGui import QTransform

from constants import PALETTE_MIME, SHAPES, DEFAULTS

A4_WIDTH_MM = 210
A4_HEIGHT_MM = 297
SCREEN_DPI = 96  # Typical desktop DPI


def mm_to_px(mm: float, dpi: float = SCREEN_DPI) -> float:
    return mm / 25.4 * dpi
from items import (
    RectItem,
    SplitRoundedRectItem,
    EllipseItem,
    LineItem,
    TextItem,
    TriangleItem,
    DiamondItem,
    BlockArrowItem,
    GroupItem,
    ResizableItem,
    ResizeHandle,
    RotationHandle,
)

# Minimum mouse movement (in scene coordinates) required before
# showing duplicates when Ctrl+dragging selected items.
DUPLICATE_DRAG_THRESHOLD = 10.0


class CornerRadiusDialog(QtWidgets.QDialog):
    valueChanged = QtCore.Signal(int)

    def __init__(self, radius: float, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Corner radius")

        layout = QtWidgets.QFormLayout(self)

        self.slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider.setRange(0, 50)
        self.slider.setValue(int(radius))
        self.slider.setTracking(True)
        self.label = QtWidgets.QLabel(str(int(radius)))
        self.label.setFixedWidth(40)
        radius_layout = QtWidgets.QHBoxLayout()
        radius_layout.addWidget(self.slider)
        radius_layout.addWidget(self.label)
        layout.addRow("radius", radius_layout)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        self.slider.valueChanged.connect(self._on_slider_value_changed)

    def value(self) -> int:
        return self.slider.value()

    def _on_slider_value_changed(self, value: int) -> None:
        self.label.setText(str(value))
        self.valueChanged.emit(value)


class OpacityDialog(QtWidgets.QDialog):
    valueChanged = QtCore.Signal(float)

    def __init__(self, value: float, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Fill opacity")

        self._value = value

        layout = QtWidgets.QVBoxLayout(self)

        slider_layout = QtWidgets.QHBoxLayout()
        self.slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(round(value * 100))
        self.slider.setTracking(True)
        slider_layout.addWidget(self.slider, stretch=1)

        self.display = QtWidgets.QLineEdit(f"{value:.2f}")
        self.display.setReadOnly(True)
        self.display.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        self.display.setFixedWidth(60)
        slider_layout.addWidget(self.display)

        layout.addLayout(slider_layout)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.slider.valueChanged.connect(self._on_slider_value_changed)

    def _on_slider_value_changed(self, slider_value: int) -> None:
        self._value = slider_value / 100.0
        self.display.setText(f"{self._value:.2f}")
        self.valueChanged.emit(self._value)

    def value(self) -> float:
        return self._value


class TrackingScene(QtWidgets.QGraphicsScene):
    """QGraphicsScene that keeps strong refs to added items."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._owned_items: set[QtWidgets.QGraphicsItem] = set()

    def addItem(self, item: QtWidgets.QGraphicsItem) -> None:  # type: ignore[override]
        super().addItem(item)
        self._owned_items.add(item)

    def removeItem(self, item: QtWidgets.QGraphicsItem) -> None:  # type: ignore[override]
        super().removeItem(item)
        self._owned_items.discard(item)

    def clear(self) -> None:  # type: ignore[override]
        super().clear()
        self._owned_items.clear()


class A4PageItem(QtWidgets.QGraphicsRectItem):
    """QGraphicsRectItem representing a single A4 page with a grid."""

    def __init__(
        self,
        width: float,
        height: float,
        *,
        margin_mm: float = 12.0,
        grid_px: int = 50,
        subgrid_px: int = 10,
        index: tuple[int, int] = (0, 0),
        master_origin: QtCore.QPointF = QtCore.QPointF(),
    ):
        super().__init__(0.0, 0.0, width, height)
        self.setBrush(QtGui.QBrush(QtCore.Qt.GlobalColor.white))
        self.setPen(QtCore.Qt.PenStyle.NoPen)
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        self.setZValue(-100)

        margin_px = mm_to_px(margin_mm)
        self._margins = QtCore.QMarginsF(margin_px, margin_px, margin_px, margin_px)
        self._grid_visible = True
        self._grid_px = max(1, grid_px)
        self._subgrid_px = max(1, subgrid_px)
        self.index: tuple[int, int] = index
        self._master_origin = QtCore.QPointF(master_origin)
        self._transition_edges: set[str] = set()
        self._neighbors: dict[str, bool] = {
            "left": False,
            "right": False,
            "top": False,
            "bottom": False,
        }
        self._outline_pen = QtGui.QPen(QtGui.QColor(0, 0, 0, 120))
        self._outline_pen.setStyle(QtCore.Qt.PenStyle.DashLine)
        self._outline_pen.setWidthF(0)
        self._outline_pen.setCapStyle(QtCore.Qt.PenCapStyle.FlatCap)
        self._outline_pen.setJoinStyle(QtCore.Qt.PenJoinStyle.MiterJoin)

    def set_grid_spacing(self, grid_px: int, subgrid_px: int) -> None:
        self._grid_px = max(1, grid_px)
        self._subgrid_px = max(1, subgrid_px)
        self.update()

    def set_grid_visible(self, visible: bool) -> None:
        self._grid_visible = visible
        self.update()

    def set_master_origin(self, origin: QtCore.QPointF) -> None:
        if self._master_origin == origin:
            return
        self._master_origin = QtCore.QPointF(origin)
        self.update()

    def set_transition_edges(self, edges: set[str]) -> None:
        if self._transition_edges == edges:
            return
        self._transition_edges = set(edges)
        self.update()

    def set_outline_neighbors(
        self, *, left: bool, right: bool, top: bool, bottom: bool
    ) -> None:
        if (
            self._neighbors["left"] == left
            and self._neighbors["right"] == right
            and self._neighbors["top"] == top
            and self._neighbors["bottom"] == bottom
        ):
            return
        self._neighbors["left"] = left
        self._neighbors["right"] = right
        self._neighbors["top"] = top
        self._neighbors["bottom"] = bottom
        self.update()

    def paint(
        self,
        painter: QtGui.QPainter,
        option: QtWidgets.QStyleOptionGraphicsItem,
        widget=None,
    ) -> None:
        super().paint(painter, option, widget)

        page_rect = self.rect()

        painter.save()
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)

        outline_vertical = QtGui.QPen(self._outline_pen)
        outline_horizontal = QtGui.QPen(self._outline_pen)

        dash_pattern = outline_vertical.dashPattern()
        dash_period = sum(dash_pattern) if dash_pattern else 0.0
        scene_pos = self.scenePos()

        if dash_period > 0.0:
            vertical_offset = math.fmod(
                scene_pos.y() - self._master_origin.y(), dash_period
            )
            horizontal_offset = math.fmod(
                scene_pos.x() - self._master_origin.x(), dash_period
            )
            if vertical_offset < 0.0:
                vertical_offset += dash_period
            if horizontal_offset < 0.0:
                horizontal_offset += dash_period
            outline_vertical.setDashOffset(vertical_offset)
            outline_horizontal.setDashOffset(horizontal_offset)

        transition_vertical = QtGui.QPen(outline_vertical)
        transition_horizontal = QtGui.QPen(outline_horizontal)
        transition_vertical.setColor(QtGui.QColor(0, 0, 0, 160))
        transition_horizontal.setColor(QtGui.QColor(0, 0, 0, 160))

        has_left_neighbor = self._neighbors["left"]
        has_right_neighbor = self._neighbors["right"]
        has_top_neighbor = self._neighbors["top"]
        has_bottom_neighbor = self._neighbors["bottom"]

        edge_segments: list[tuple[str, QtCore.QPointF, QtCore.QPointF]] = []
        if not has_left_neighbor:
            edge_segments.append(
                (
                    "left",
                    QtCore.QPointF(page_rect.left(), page_rect.top()),
                    QtCore.QPointF(page_rect.left(), page_rect.bottom()),
                )
            )
        edge_segments.append(
            (
                "right",
                QtCore.QPointF(page_rect.right(), page_rect.top()),
                QtCore.QPointF(page_rect.right(), page_rect.bottom()),
            )
        )
        if not has_top_neighbor:
            edge_segments.append(
                (
                    "top",
                    QtCore.QPointF(page_rect.left(), page_rect.top()),
                    QtCore.QPointF(page_rect.right(), page_rect.top()),
                )
            )
        edge_segments.append(
            (
                "bottom",
                QtCore.QPointF(page_rect.left(), page_rect.bottom()),
                QtCore.QPointF(page_rect.right(), page_rect.bottom()),
            )
        )

        for edge, start, end in edge_segments:
            if edge in ("left", "right"):
                pen = (
                    transition_vertical
                    if edge in self._transition_edges
                    else outline_vertical
                )
            else:
                pen = (
                    transition_horizontal
                    if edge in self._transition_edges
                    else outline_horizontal
                )
            painter.setPen(pen)
            painter.drawLine(start, end)

        painter.restore()

        if not self._grid_visible:
            return

        painter.save()
        painter.setClipRect(page_rect)

        origin_scene = self.scenePos()
        master_origin = self._master_origin

        def _first_position(
            spacing: float,
            orientation: str,
        ) -> float:
            if spacing <= 0:
                return 0.0
            if orientation == "vertical":
                start = page_rect.left()
                offset = (origin_scene.x() - master_origin.x()) % spacing
            else:
                start = page_rect.top()
                offset = (origin_scene.y() - master_origin.y()) % spacing
            if math.isclose(offset, spacing, abs_tol=1e-6) or math.isclose(offset, 0.0, abs_tol=1e-6):
                offset = 0.0
            return start + (spacing - offset) % spacing

        def _draw_lines(spacing: float, orientation: str, skip_main: bool) -> None:
            if spacing <= 0:
                return
            if orientation == "vertical":
                start = page_rect.left()
                end = page_rect.right()
                origin_value = origin_scene.x()
                first = _first_position(spacing, orientation)
                pos = first
                while pos <= end + 0.5:
                    if skip_main:
                        scene_value = origin_value + (pos - start)
                        distance = scene_value - master_origin.x()
                        nearest = round(distance / self._grid_px) * self._grid_px
                        if math.isclose(distance, nearest, abs_tol=0.3):
                            pos += spacing
                            continue
                    painter.drawLine(pos, page_rect.top(), pos, page_rect.bottom())
                    pos += spacing
            else:
                start = page_rect.top()
                end = page_rect.bottom()
                origin_value = origin_scene.y()
                first = _first_position(spacing, orientation)
                pos = first
                while pos <= end + 0.5:
                    if skip_main:
                        scene_value = origin_value + (pos - start)
                        distance = scene_value - master_origin.y()
                        nearest = round(distance / self._grid_px) * self._grid_px
                        if math.isclose(distance, nearest, abs_tol=0.3):
                            pos += spacing
                            continue
                    painter.drawLine(page_rect.left(), pos, page_rect.right(), pos)
                    pos += spacing

        subgrid_pen = QtGui.QPen(QtGui.QColor(0, 0, 0, 30))
        subgrid_pen.setWidthF(0)
        painter.setPen(subgrid_pen)

        _draw_lines(self._subgrid_px, "vertical", True)
        _draw_lines(self._subgrid_px, "horizontal", True)

        grid_pen = QtGui.QPen(QtGui.QColor(0, 0, 0, 80))
        grid_pen.setWidthF(0)
        painter.setPen(grid_pen)

        _draw_lines(self._grid_px, "vertical", False)
        _draw_lines(self._grid_px, "horizontal", False)

        painter.restore()


class CanvasView(QtWidgets.QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        self.setDragMode(QtWidgets.QGraphicsView.DragMode.RubberBandDrag)
        # Style the selection rubber band with a blue dashed outline
        self.viewport().setStyleSheet(
            "QRubberBand { border: 1px dashed #14b5ff; }"
        )
        self.setAcceptDrops(True)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setViewportUpdateMode(
            QtWidgets.QGraphicsView.ViewportUpdateMode.FullViewportUpdate
        )

        scene = TrackingScene(self)
        self._scene_padding = 200
        scene.setSceneRect(
            -self._scene_padding,
            -self._scene_padding,
            self._scene_padding * 2,
            self._scene_padding * 2,
        )
        scene.changed.connect(self._update_scene_rect)
        self.setScene(scene)
        self.setBackgroundBrush(QtGui.QColor("#f0f0f0"))
        self._grid_size = 50
        self._grid_size_min = 10
        self._show_grid = True
        self._page_width = mm_to_px(A4_WIDTH_MM, SCREEN_DPI)
        self._page_height = mm_to_px(A4_HEIGHT_MM, SCREEN_DPI)
        self._master_index: tuple[int, int] = (0, 0)
        self._pages: dict[tuple[int, int], A4PageItem] = {}
        self._master_origin = self._page_top_left_for_index(self._master_index)
        self._page_item = self._create_page_item(self._master_index)
        self._pages[self._master_index] = self._page_item
        scene.addItem(self._page_item)
        self._update_transition_edges()
        QtCore.QTimer.singleShot(0, self._fit_view_to_page)
        self._update_scene_rect()

        self._panning = False
        self._pan_start = QtCore.QPointF()
        self._prev_drag_mode = self.dragMode()
        self._right_button_pressed = False
        self._suppress_context_menu = False

    def _page_top_left_for_index(self, index: tuple[int, int]) -> QtCore.QPointF:
        row, col = index
        base_x = -self._page_width / 2.0
        base_y = -self._page_height / 2.0
        return QtCore.QPointF(
            base_x + col * self._page_width,
            base_y + row * self._page_height,
        )

    def _page_index_for_point(self, point: QtCore.QPointF) -> tuple[int, int]:
        base_x = -self._page_width / 2.0
        base_y = -self._page_height / 2.0
        col = math.floor((point.x() - base_x) / self._page_width)
        row = math.floor((point.y() - base_y) / self._page_height)
        return (row, col)

    def _create_page_item(self, index: tuple[int, int]) -> A4PageItem:
        page = A4PageItem(
            self._page_width,
            self._page_height,
            margin_mm=12.0,
            grid_px=self._grid_size,
            subgrid_px=self._grid_size_min,
            index=index,
            master_origin=self._master_origin,
        )
        top_left = self._page_top_left_for_index(index)
        page.setPos(top_left)
        page.set_grid_visible(self._show_grid)
        return page

    def _add_page(
        self, index: tuple[int, int], *, update_edges: bool = True
    ) -> A4PageItem:
        existing = self._pages.get(index)
        if existing is not None:
            existing.set_master_origin(self._master_origin)
            return existing
        page = self._create_page_item(index)
        self.scene().addItem(page)
        self._pages[index] = page
        if update_edges:
            self._update_transition_edges()
        return page

    def _ensure_pages_between_master(self, target_index: tuple[int, int]) -> None:
        master_row, master_col = self._master_index
        target_row, target_col = target_index
        min_row = min(master_row, target_row)
        max_row = max(master_row, target_row)
        min_col = min(master_col, target_col)
        max_col = max(master_col, target_col)

        added_any = False
        for row in range(min_row, max_row + 1):
            for col in range(min_col, max_col + 1):
                index = (row, col)
                if index not in self._pages:
                    added_any = True
                self._add_page(index, update_edges=False)
        if added_any:
            self._update_transition_edges()

    def _update_transition_edges(self) -> None:
        master_page = self._pages.get(self._master_index)
        if master_page is None:
            return
        for (row, col), page in self._pages.items():
            page.set_outline_neighbors(
                left=(row, col - 1) in self._pages,
                right=(row, col + 1) in self._pages,
                top=(row - 1, col) in self._pages,
                bottom=(row + 1, col) in self._pages,
            )
        master_edges: set[str] = set()
        master_row, master_col = self._master_index
        for (row, col), page in self._pages.items():
            if (row, col) == self._master_index:
                continue
            edges: set[str] = set()
            if row == master_row:
                if col == master_col + 1:
                    edges.add("left")
                    master_edges.add("right")
                elif col == master_col - 1:
                    edges.add("right")
                    master_edges.add("left")
            if col == master_col:
                if row == master_row + 1:
                    edges.add("top")
                    master_edges.add("bottom")
                elif row == master_row - 1:
                    edges.add("bottom")
                    master_edges.add("top")
            page.set_transition_edges(edges)
        master_page.set_transition_edges(master_edges)

    def _ensure_page_for_item(
        self, item: QtWidgets.QGraphicsItem, drop_reference: QtCore.QPointF | None
    ) -> A4PageItem:
        rect = item.sceneBoundingRect()
        page: A4PageItem | None = None
        for existing in self._pages.values():
            page_rect = existing.mapRectToScene(existing.rect())
            if page_rect.contains(rect):
                page = existing
                break

        indices_to_connect: set[tuple[int, int]] = set()

        if page is None:
            reference = drop_reference if drop_reference is not None else rect.center()
            index = self._page_index_for_point(reference)
            page = self._add_page(index)
            indices_to_connect.add(index)
            if not page.mapRectToScene(page.rect()).contains(rect):
                center_index = self._page_index_for_point(rect.center())
                page = self._add_page(center_index)
                indices_to_connect.add(center_index)
        if page is not None:
            indices_to_connect.add(page.index)

        for index in indices_to_connect:
            self._ensure_pages_between_master(index)

        self._prune_empty_pages()
        self._update_scene_rect()
        assert page is not None
        return page

    def _collect_canvas_content_items(self) -> list[QtWidgets.QGraphicsItem]:
        scene = self.scene()
        if scene is None:
            return []
        items: list[QtWidgets.QGraphicsItem] = []
        for item in scene.items():
            if isinstance(item, A4PageItem):
                continue
            if item.__class__.__name__.endswith("Handle"):
                continue
            items.append(item)
        return items

    def _prune_empty_pages(self) -> bool:
        scene = self.scene()
        if scene is None:
            return False
        content_items = self._collect_canvas_content_items()
        master_row, master_col = self._master_index

        content_indices: set[tuple[int, int]] = set()
        for index, page in self._pages.items():
            page_rect = page.mapRectToScene(page.rect())
            has_item = any(
                item.sceneBoundingRect().intersects(page_rect)
                for item in content_items
                if item.scene() is scene
            )
            if has_item:
                content_indices.add(index)

        required_indices: set[tuple[int, int]] = {self._master_index}
        for row, col in content_indices:
            min_row = min(master_row, row)
            max_row = max(master_row, row)
            min_col = min(master_col, col)
            max_col = max(master_col, col)
            for r in range(min_row, max_row + 1):
                for c in range(min_col, max_col + 1):
                    required_indices.add((r, c))

        removed = False
        for index, page in list(self._pages.items()):
            if index in required_indices:
                continue
            self._pages.pop(index, None)
            scene.removeItem(page)
            removed = True
        if removed:
            self._update_transition_edges()
        return removed

    def _ensure_pages_for_items(
        self, items: list[QtWidgets.QGraphicsItem]
    ) -> None:
        for item in items:
            if isinstance(item, A4PageItem):
                continue
            if item.__class__.__name__.endswith("Handle"):
                continue
            if item.parentItem() is not None:
                continue
            self._ensure_page_for_item(item, item.sceneBoundingRect().center())

    def _fit_view_to_page(self) -> None:
        if self._page_item is None:
            return
        page_scene_rect = self._page_item.mapRectToScene(self._page_item.rect())
        padded = page_scene_rect.adjusted(-80, -80, 80, 80)
        if padded.isValid() and padded.width() > 0 and padded.height() > 0:
            self.fitInView(padded, QtCore.Qt.AspectRatioMode.KeepAspectRatio)
        self.centerOn(self._page_item)

    def clear_canvas(self):
        """Remove all items from the scene."""
        scene = self.scene()
        for item in list(scene.items()):
            if isinstance(item, A4PageItem):
                continue
            if item.__class__.__name__.endswith("Handle"):
                continue
            if item.parentItem() is not None:
                continue
            scene.removeItem(item)
        self._prune_empty_pages()
        self._update_scene_rect()

    def ensure_pages_for_scene_items(self) -> None:
        """Ensure every top-level scene item has an A4 page beneath it."""
        scene = self.scene()
        if scene is None:
            return
        self._ensure_pages_for_items(scene.items())

    def drawBackground(self, painter: QtGui.QPainter, rect: QtCore.QRectF):
        super().drawBackground(painter, rect)

    def set_grid_visible(self, visible: bool):
        self._show_grid = visible
        for page in self._pages.values():
            page.set_grid_visible(visible)
        self.viewport().update()

    def _update_scene_rect(self):
        scene = self.scene()
        padding = self._scene_padding
        items_rect = scene.itemsBoundingRect()
        viewport_rect = self.mapToScene(self.viewport().rect()).boundingRect()
        if items_rect.isNull():
            combined = viewport_rect
        else:
            combined = items_rect.united(viewport_rect)
        if combined.isNull():
            new_rect = QtCore.QRectF(
                -padding,
                -padding,
                padding * 2,
                padding * 2,
            )
        else:
            new_rect = combined.adjusted(-padding, -padding, padding, padding)
        if new_rect != scene.sceneRect():
            scene.setSceneRect(new_rect)
            # ensure newly exposed areas are repainted so drag handles don't leave trails
            self.viewport().update()

    def resizeEvent(self, event: QtGui.QResizeEvent):
        """Ensure scene rect grows with the view."""
        super().resizeEvent(event)
        self._update_scene_rect()

    def add_shape(
        self,
        shape: str,
        scene_pos: QtCore.QPointF,
        snap_to_grid: bool = True,
    ) -> QtWidgets.QGraphicsItem | None:
        normalized = shape.strip()
        if normalized not in SHAPES:
            return None

        x = scene_pos.x()
        y = scene_pos.y()
        w, h = DEFAULTS[normalized]

        if snap_to_grid:
            size = self._grid_size
            x = round(x / size) * size
            y = round(y / size) * size
            if normalized in ("Line", "Arrow"):
                w = round(w / size) * size

        drop_reference = QtCore.QPointF(x + w / 2.0, y + h / 2.0)

        if normalized == "Rectangle":
            item = RectItem(x, y, w, h)
        elif normalized == "Rounded Rectangle":
            item = RectItem(x, y, w, h, 15.0, 15.0)
        elif normalized == "Split Rounded Rectangle":
            item = SplitRoundedRectItem(x, y, w, h, 15.0, 15.0)
        elif normalized in ("Circle", "Ellipse"):
            item = EllipseItem(x, y, w, h)
        elif normalized == "Triangle":
            item = TriangleItem(x, y, w, h)
        elif normalized == "Diamond":
            item = DiamondItem(x, y, w, h)
        elif normalized == "Line":
            item = LineItem(x, y, w)
        elif normalized == "Arrow":
            item = LineItem(x, y, w, arrow_end=True)
        elif normalized == "Block Arrow":
            item = BlockArrowItem(x, y, w, h)
        elif normalized == "Text":
            item = TextItem(x, y, w, h)
        else:
            return None

        item.setData(0, normalized)
        self.scene().addItem(item)
        item.setSelected(True)
        self._ensure_page_for_item(item, drop_reference)
        self._update_scene_rect()
        return item

    def add_shape_at_view_center(self, shape: str) -> QtWidgets.QGraphicsItem | None:
        normalized = shape.strip()
        if normalized not in SHAPES:
            return None

        center = self.mapToScene(self.viewport().rect().center())
        w, h = DEFAULTS[normalized]
        if normalized in ("Line", "Arrow"):
            pos = QtCore.QPointF(center.x() - w / 2.0, center.y())
        else:
            pos = QtCore.QPointF(center.x() - w / 2.0, center.y() - h / 2.0)
        return self.add_shape(normalized, pos, snap_to_grid=False)

    # --- Drag and drop from the palette ---
    def dragEnterEvent(self, event: QtGui.QDragEnterEvent):
        md = event.mimeData()
        if md.hasFormat(PALETTE_MIME) or md.hasText():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent):
        if event.mimeData().hasFormat(PALETTE_MIME) or event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QtGui.QDropEvent):
        md = event.mimeData()
        text = ""
        if md.hasFormat(PALETTE_MIME):
            text = str(bytes(md.data(PALETTE_MIME)).decode("utf-8"))
        elif md.hasText():
            text = md.text()

        shape = text.strip()
        if shape not in SHAPES:
            super().dropEvent(event)
            return

        scene_pos = self.mapToScene(event.position().toPoint())
        snap = not (
            event.keyboardModifiers() & QtCore.Qt.KeyboardModifier.AltModifier
        )
        item = self.add_shape(shape, scene_pos, snap_to_grid=snap)
        if item is not None:
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    # --- Duplicate selected items with Ctrl+drag ---
    def mousePressEvent(self, event: QtGui.QMouseEvent):
        if event.button() == QtCore.Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start = event.position()
            self._prev_drag_mode = self.dragMode()
            self.setDragMode(QtWidgets.QGraphicsView.DragMode.NoDrag)
            self.viewport().setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() == QtCore.Qt.MouseButton.RightButton:
            self._right_button_pressed = True
            self._pan_start = event.position()
            self._prev_drag_mode = self.dragMode()
            self._suppress_context_menu = False
            event.accept()
            return
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            mods = event.modifiers()
            if mods & (
                QtCore.Qt.KeyboardModifier.ControlModifier
                | QtCore.Qt.KeyboardModifier.ShiftModifier
            ):
                item = self.itemAt(event.pos())
                if item:
                    if (
                        mods & QtCore.Qt.KeyboardModifier.ControlModifier
                        and item.isSelected()
                    ):
                        selected = self.scene().selectedItems()
                        if selected:
                            # Store initial state but postpone cloning until the mouse
                            # has moved far enough to avoid duplicates appearing in place.
                            self._dup_source = list(selected)
                            self._dup_items = None
                            self._dup_orig = None
                            self._dup_start = self.mapToScene(
                                event.position().toPoint()
                            )
                        event.accept()
                        return
                    else:
                        item.setSelected(True)
                        event.accept()
                        return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent):
        
        item = self.itemAt(event.position().toPoint())
        if item and item.flags() & QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable:
            self.viewport().setCursor(QtCore.Qt.CursorShape.SizeAllCursor)
        else:
            self.viewport().setCursor(QtCore.Qt.CursorShape.ArrowCursor)

        if self._panning or self._right_button_pressed:
            delta = event.position() - self._pan_start
            if (
                self._right_button_pressed
                and not self._panning
                and delta.manhattanLength() > 0
            ):
                self._panning = True
                self.setDragMode(QtWidgets.QGraphicsView.DragMode.NoDrag)
                self.viewport().setCursor(
                    QtCore.Qt.CursorShape.ClosedHandCursor
                )
            if self._panning:
                self._pan_start = event.position()
                hbar = self.horizontalScrollBar()
                vbar = self.verticalScrollBar()
                hbar.setValue(hbar.value() - int(delta.x()))
                vbar.setValue(vbar.value() - int(delta.y()))
                event.accept()
                return
        if getattr(self, "_dup_source", None):
            pos = self.mapToScene(event.position().toPoint())
            delta = pos - self._dup_start
            if self._dup_items is None:
                # Only create clones after surpassing the threshold.
                if delta.manhattanLength() < DUPLICATE_DRAG_THRESHOLD:
                    event.accept()
                    return
                self._dup_items = []
                self._dup_orig = []
                for it in self._dup_source:
                    clone = self._clone_item(it)
                    if clone:
                        self.scene().addItem(clone)
                        self._dup_items.append(clone)
                        self._dup_orig.append(clone.pos())
                self.scene().clearSelection()
                for it in self._dup_items:
                    it.setSelected(True)
            for it, start in zip(self._dup_items, self._dup_orig):
                it.setPos(start + delta)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent):
        if event.button() == QtCore.Qt.MouseButton.RightButton:
            if self._panning:
                self._panning = False
                self._right_button_pressed = False
                self.setDragMode(self._prev_drag_mode)
                self.viewport().setCursor(
                    QtCore.Qt.CursorShape.ArrowCursor
                )
                self._suppress_context_menu = True
                event.accept()
                return
            if self._right_button_pressed:
                self._right_button_pressed = False
                event.accept()
                return
        if (
            event.button() == QtCore.Qt.MouseButton.MiddleButton and self._panning
        ):
            self._panning = False
            self.setDragMode(self._prev_drag_mode)
            self.viewport().setCursor(QtCore.Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            if getattr(self, "_dup_items", None):
                self._dup_items = []
                self._dup_orig = []
                self._dup_source = []
                self._ensure_pages_for_items(self.scene().selectedItems())
                event.accept()
                return
            if getattr(self, "_dup_source", None):
                # Ctrl+click without enough movement -> no duplication
                self._dup_source = []
                event.accept()
                return
        super().mouseReleaseEvent(event)
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._ensure_pages_for_items(self.scene().selectedItems())

    def _clone_item(self, item: QtWidgets.QGraphicsItem):
        if isinstance(item, RectItem):
            r = item.rect()
            clone = RectItem(item.x(), item.y(), r.width(), r.height(), getattr(item, "rx", 0.0), getattr(item, "ry", 0.0))
            clone.setBrush(item.brush())
            clone.setPen(item.pen())
        elif isinstance(item, SplitRoundedRectItem):
            r = item.rect()
            clone = SplitRoundedRectItem(
                item.x(),
                item.y(),
                r.width(),
                r.height(),
                getattr(item, "rx", 0.0),
                getattr(item, "ry", 0.0),
            )
            clone.setTopBrush(item.topBrush())
            clone.setBottomBrush(item.bottomBrush())
            clone.set_divider_ratio(item.divider_ratio())
            clone.setPen(item.pen())
        elif isinstance(item, EllipseItem):
            r = item.rect()
            clone = EllipseItem(item.x(), item.y(), r.width(), r.height())
            clone.setBrush(item.brush())
            clone.setPen(item.pen())
        elif isinstance(item, TriangleItem):
            br = item.boundingRect()
            clone = TriangleItem(item.x(), item.y(), br.width(), br.height())
            clone.setBrush(item.brush())
            clone.setPen(item.pen())
        elif isinstance(item, DiamondItem):
            br = item.boundingRect()
            clone = DiamondItem(item.x(), item.y(), br.width(), br.height())
            clone.setBrush(item.brush())
            clone.setPen(item.pen())
        elif isinstance(item, LineItem):
            clone = LineItem(
                item.x(),
                item.y(),
                points=[QtCore.QPointF(p) for p in item._points],
                arrow_start=getattr(item, "arrow_start", False),
                arrow_end=getattr(item, "arrow_end", False),
            )
            clone.setPen(item.pen())
        elif isinstance(item, TextItem):
            br = item.boundingRect()
            clone = TextItem(item.x(), item.y(), br.width(), br.height())
            clone.setPlainText(item.toPlainText())
            clone.setFont(item.font())
            clone.setDefaultTextColor(item.defaultTextColor())
            br = clone.boundingRect()
            clone.setTransformOriginPoint(br.width() / 2.0, br.height() / 2.0)
            clone.setScale(item.scale())
        else:
            return None
        clone.setRotation(item.rotation())
        clone.setData(0, item.data(0))
        return clone

    # --- Mouse wheel zooming and scrolling ---
    def wheelEvent(self, event: QtGui.QWheelEvent):
        mods = event.modifiers()
        if mods & (
            QtCore.Qt.KeyboardModifier.ControlModifier
            | QtCore.Qt.KeyboardModifier.AltModifier
        ):
            anchor = self.transformationAnchor()
            self.setTransformationAnchor(
                QtWidgets.QGraphicsView.ViewportAnchor.AnchorUnderMouse
            )
            delta = event.angleDelta().y()
            if delta == 0:
                delta = event.angleDelta().x()
            factor = 1.2 if delta > 0 else 1 / 1.2
            self.scale(factor, factor)
            self.setTransformationAnchor(anchor)
            self._update_scene_rect()
            event.accept()
            return
        super().wheelEvent(event)

    def _group_selected_items(self):
        selected = self.scene().selectedItems()
        if len(selected) < 2:
            return

        br = QtCore.QRectF()
        for it in selected:
            br = br.united(it.sceneBoundingRect())

        group = GroupItem()
        group.setPos(br.topLeft())
        self.scene().addItem(group)

        for it in selected:
            group.addToGroup(it)
            it.setSelected(False)
            it.setFlag(
                QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False
            )
            it.setFlag(
                QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False
            )
            if isinstance(it, ResizableItem):
                it.hide_handles()

        group.setTransformOriginPoint(group.boundingRect().center())
        group.setSelected(True)
        group.update_handles()
        self._update_scene_rect()

    def _ungroup_selected_items(self):
        selected = self.scene().selectedItems()
        changed = False
        for it in selected:
            if isinstance(it, GroupItem):
                it.setSelected(False)
                children = [
                    c
                    for c in it.childItems()
                    if not isinstance(c, (ResizeHandle, RotationHandle))
                ]
                for child in children:
                    it.removeFromGroup(child)
                    child.setFlag(
                        QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable,
                        True,
                    )
                    child.setFlag(
                        QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable,
                        True,
                    )
                    child.setSelected(False)
                self.scene().removeItem(it)
                changed = True
        if changed:
            self.scene().clearSelection()
            self._prune_empty_pages()
            self._update_scene_rect()

    # --- Keyboard shortcut to delete selected items ---
    def keyPressEvent(self, event: QtGui.QKeyEvent):
        if event.key() == QtCore.Qt.Key.Key_Delete:
            selected = self.scene().selectedItems()
            if selected:
                for it in selected:
                    self.scene().removeItem(it)
                self._prune_empty_pages()
                self._update_scene_rect()
                event.accept()
                return
        mods = event.modifiers()
        if (
            event.key() == QtCore.Qt.Key.Key_G
            and mods == QtCore.Qt.KeyboardModifier.ControlModifier
        ):
            self._group_selected_items()
            event.accept()
            return
        if (
            event.key() == QtCore.Qt.Key.Key_G
            and mods
            == (
                QtCore.Qt.KeyboardModifier.ControlModifier
                | QtCore.Qt.KeyboardModifier.ShiftModifier
            )
        ):
            self._ungroup_selected_items()
            event.accept()
            return
        super().keyPressEvent(event)

    # --- Alignment helpers ---
    def _align_items(self, items, mode: str):
        brs = [it.sceneBoundingRect() for it in items]
        if mode == "grid":
            size = self._grid_size
            for it, br in zip(items, brs):
                new_x = round(br.left() / size) * size
                new_y = round(br.top() / size) * size
                it.moveBy(new_x - br.left(), new_y - br.top())
            return
        if mode == "left":
            target = min(br.left() for br in brs)
            for it, br in zip(items, brs):
                it.moveBy(target - br.left(), 0)
        elif mode == "hcenter":
            target = sum(br.center().x() for br in brs) / len(brs)
            for it, br in zip(items, brs):
                it.moveBy(target - br.center().x(), 0)
        elif mode == "right":
            target = max(br.right() for br in brs)
            for it, br in zip(items, brs):
                it.moveBy(target - br.right(), 0)
        elif mode == "top":
            target = min(br.top() for br in brs)
            for it, br in zip(items, brs):
                it.moveBy(0, target - br.top())
        elif mode == "vcenter":
            target = sum(br.center().y() for br in brs) / len(brs)
            for it, br in zip(items, brs):
                it.moveBy(0, target - br.center().y())
        elif mode == "bottom":
            target = max(br.bottom() for br in brs)
            for it, br in zip(items, brs):
                it.moveBy(0, target - br.bottom())

    def _create_color_action(
        self,
        menu: QtWidgets.QMenu,
        text: str,
        title: str,
        color_getter: Callable[[], QtGui.QColor],
        color_setter: Callable[[QtGui.QColor], None],
    ) -> tuple[QtGui.QAction, Callable[[], None]]:
        action = menu.addAction(text)

        def callback() -> None:
            color = QtWidgets.QColorDialog.getColor(color_getter(), self, title)
            if color.isValid():
                color_setter(color)

        return action, callback

    def _create_double_action(
        self,
        menu: QtWidgets.QMenu,
        text: str,
        dialog_title: str,
        label: str,
        value_getter: Callable[[], float],
        value_setter: Callable[[float], None],
        minimum: float,
        maximum: float,
        decimals: int,
    ) -> tuple[QtGui.QAction, Callable[[], None]]:
        action = menu.addAction(text)

        def callback() -> None:
            value, ok = QtWidgets.QInputDialog.getDouble(
                self,
                dialog_title,
                label,
                value_getter(),
                minimum,
                maximum,
                decimals,
            )
            if ok:
                value_setter(value)

        return action, callback

    def _create_shape_style_actions(
        self, menu: QtWidgets.QMenu, item: QtWidgets.QGraphicsItem
    ) -> dict[QtGui.QAction, Callable[[], None]]:
        actions: dict[QtGui.QAction, Callable[[], None]] = {}

        def add_fill_actions() -> None:
            fill_action, fill_callback = self._create_color_action(
                menu,
                "Set fill color…",
                "Fill color",
                lambda item=item: item.brush().color(),
                lambda color, item=item: item.setBrush(color),
            )
            actions[fill_action] = fill_callback

            def opacity_getter(item=item) -> float:
                brush = item.brush()
                if brush.style() == QtCore.Qt.BrushStyle.NoBrush:
                    return 1.0
                return brush.color().alphaF()

            def opacity_setter(value: float, item=item) -> None:
                brush = item.brush()
                color = brush.color()
                color.setAlphaF(value)
                item.setBrush(color)

            opacity_action = menu.addAction("Set fill opacity…")

            def opacity_callback(item=item) -> None:
                initial_opacity = opacity_getter()
                dialog = OpacityDialog(initial_opacity, self)

                def handle_value_changed(value: float, item=item) -> None:
                    opacity_setter(value, item)

                dialog.valueChanged.connect(handle_value_changed)
                result = dialog.exec()
                if result == QtWidgets.QDialog.DialogCode.Accepted:
                    opacity_setter(dialog.value(), item)
                else:
                    opacity_setter(initial_opacity, item)

            actions[opacity_action] = opacity_callback

        def add_stroke_actions() -> None:
            def stroke_color_setter(color: QtGui.QColor, item=item) -> None:
                pen = item.pen()
                pen.setColor(color)
                item.setPen(pen)
                item.update()

            stroke_action, stroke_callback = self._create_color_action(
                menu,
                "Set stroke color…",
                "Stroke color",
                lambda item=item: item.pen().color(),
                stroke_color_setter,
            )
            actions[stroke_action] = stroke_callback

            def width_setter(value: float, item=item) -> None:
                pen = item.pen()
                pen.setWidthF(value)
                item.setPen(pen)
                item.update()

            width_action, width_callback = self._create_double_action(
                menu,
                "Set stroke width…",
                "Stroke width",
                "Width:",
                lambda item=item: item.pen().widthF(),
                width_setter,
                0.1,
                50.0,
                1,
            )
            actions[width_action] = width_callback

        def add_corner_action() -> None:
            corner_action = menu.addAction("Set corner radius…")

            def corner_callback(item=item) -> None:
                initial_rx = item.rx
                initial_ry = item.ry
                dlg = CornerRadiusDialog(item.rx, self)

                def handle_value_changed(value: int, item=item) -> None:
                    radius = min(float(value), 50.0)
                    item.rx = item.ry = radius
                    item.update()

                dlg.valueChanged.connect(handle_value_changed)
                result = dlg.exec()
                if result == QtWidgets.QDialog.DialogCode.Accepted:
                    handle_value_changed(dlg.value())
                else:
                    item.rx = initial_rx
                    item.ry = initial_ry
                    item.update()

            actions[corner_action] = corner_callback

        def add_arrow_actions() -> None:
            start_action = menu.addAction("Show start arrowhead")
            start_action.setCheckable(True)
            start_action.setChecked(getattr(item, "arrow_start", False))

            def start_callback(action=start_action, item=item) -> None:
                item.set_arrow_start(action.isChecked())

            actions[start_action] = start_callback

            end_action = menu.addAction("Show end arrowhead")
            end_action.setCheckable(True)
            end_action.setChecked(getattr(item, "arrow_end", False))

            def end_callback(action=end_action, item=item) -> None:
                item.set_arrow_end(action.isChecked())

            actions[end_action] = end_callback

        def add_line_style_actions() -> None:
            style_menu = menu.addMenu("Line style")
            action_group = QtGui.QActionGroup(menu)
            action_group.setExclusive(True)
            current_style = item.pen().style()

            def make_action(text: str, style: QtCore.Qt.PenStyle) -> None:
                act = style_menu.addAction(text)
                act.setCheckable(True)
                act.setChecked(current_style == style)
                action_group.addAction(act)

                def callback(item=item, style=style) -> None:
                    setter = getattr(item, "set_pen_style", None)
                    if callable(setter):
                        setter(style)
                    else:
                        pen = QtGui.QPen(item.pen())
                        pen.setStyle(style)
                        item.setPen(pen)
                        item.update()

                actions[act] = callback

            make_action("Solid", QtCore.Qt.PenStyle.SolidLine)
            make_action("Dashed", QtCore.Qt.PenStyle.DashLine)
            make_action("Dotted", QtCore.Qt.PenStyle.DotLine)

        def add_text_actions() -> None:
            text_color_action, text_color_callback = self._create_color_action(
                menu,
                "Set text color…",
                "Text color",
                lambda item=item: item.defaultTextColor(),
                lambda color, item=item: item.setDefaultTextColor(color),
            )
            actions[text_color_action] = text_color_callback

            def font_size_setter(value: float, item=item) -> None:
                font = item.font()
                font.setPointSizeF(value)
                item.setFont(font)
                br = item.boundingRect()
                item.setTransformOriginPoint(br.width() / 2.0, br.height() / 2.0)

            font_size_action, font_size_callback = self._create_double_action(
                menu,
                "Set font size…",
                "Font size",
                "Size:",
                lambda item=item: item.font().pointSizeF(),
                font_size_setter,
                1.0,
                500.0,
                1,
            )
            actions[font_size_action] = font_size_callback

        def add_split_rect_fill_actions() -> None:
            split_item: SplitRoundedRectItem = item  # type: ignore[assignment]

            top_action, top_callback = self._create_color_action(
                menu,
                "Set top fill color…",
                "Top fill color",
                lambda item=split_item: item.topBrush().color(),
                lambda color, item=split_item: item.setTopBrush(color),
            )
            actions[top_action] = top_callback

            def top_opacity_getter(item=split_item) -> float:
                brush = item.topBrush()
                if brush.style() == QtCore.Qt.BrushStyle.NoBrush:
                    return 1.0
                return brush.color().alphaF()

            def top_opacity_setter(value: float, item=split_item) -> None:
                brush = item.topBrush()
                color = brush.color()
                color.setAlphaF(value)
                item.setTopBrush(color)

            top_opacity_action = menu.addAction("Set top fill opacity…")

            def top_opacity_callback(item=split_item) -> None:
                initial_opacity = top_opacity_getter()
                dialog = OpacityDialog(initial_opacity, self)

                def handle_value_changed(value: float, item=item) -> None:
                    top_opacity_setter(value, item)

                dialog.valueChanged.connect(handle_value_changed)
                result = dialog.exec()
                if result == QtWidgets.QDialog.DialogCode.Accepted:
                    top_opacity_setter(dialog.value(), item)
                else:
                    top_opacity_setter(initial_opacity, item)

            actions[top_opacity_action] = top_opacity_callback

            bottom_action, bottom_callback = self._create_color_action(
                menu,
                "Set bottom fill color…",
                "Bottom fill color",
                lambda item=split_item: item.bottomBrush().color(),
                lambda color, item=split_item: item.setBottomBrush(color),
            )
            actions[bottom_action] = bottom_callback

            def bottom_opacity_getter(item=split_item) -> float:
                brush = item.bottomBrush()
                if brush.style() == QtCore.Qt.BrushStyle.NoBrush:
                    return 1.0
                return brush.color().alphaF()

            def bottom_opacity_setter(value: float, item=split_item) -> None:
                brush = item.bottomBrush()
                color = brush.color()
                color.setAlphaF(value)
                item.setBottomBrush(color)

            bottom_opacity_action = menu.addAction("Set bottom fill opacity…")

            def bottom_opacity_callback(item=split_item) -> None:
                initial_opacity = bottom_opacity_getter()
                dialog = OpacityDialog(initial_opacity, self)

                def handle_value_changed(value: float, item=item) -> None:
                    bottom_opacity_setter(value, item)

                dialog.valueChanged.connect(handle_value_changed)
                result = dialog.exec()
                if result == QtWidgets.QDialog.DialogCode.Accepted:
                    bottom_opacity_setter(dialog.value(), item)
                else:
                    bottom_opacity_setter(initial_opacity, item)

            actions[bottom_opacity_action] = bottom_opacity_callback

        if isinstance(item, RectItem):
            add_fill_actions()
            add_corner_action()
            menu.addSeparator()
            add_stroke_actions()
        elif isinstance(item, SplitRoundedRectItem):
            add_split_rect_fill_actions()
            add_corner_action()
            menu.addSeparator()
            add_stroke_actions()
        elif isinstance(item, (QtWidgets.QGraphicsEllipseItem, TriangleItem, DiamondItem)):
            add_fill_actions()
            menu.addSeparator()
            add_stroke_actions()
        elif isinstance(item, LineItem):
            add_arrow_actions()
            add_line_style_actions()
            menu.addSeparator()
            add_stroke_actions()
        elif isinstance(item, TextItem):
            add_text_actions()
        else:
            add_stroke_actions()

        return actions

    # --- Context menu for adjusting colors and line width ---
    def contextMenuEvent(self, event: QtGui.QContextMenuEvent):
        if self._suppress_context_menu:
            self._suppress_context_menu = False
            event.accept()
            return
        pos = event.pos()
        item = self.itemAt(pos)
        if not item:
            menu = QtWidgets.QMenu(self)
            reset_act = menu.addAction("Reset zoom")
            action = menu.exec(event.globalPos())
            if action is reset_act:
                self.resetTransform()
            else:
                super().contextMenuEvent(event)
            return

        menu = QtWidgets.QMenu(self)

        selected = self.scene().selectedItems()
        group_act = ungroup_act = None
        if len(selected) >= 2:
            group_act = menu.addAction("Group")
        if any(isinstance(it, GroupItem) for it in selected):
            ungroup_act = menu.addAction("Ungroup")
        if group_act or ungroup_act:
            menu.addSeparator()

        align_actions = {}
        if len(selected) >= 2:
            align_menu = menu.addMenu("Align")
            align_actions[align_menu.addAction("Left")] = "left"
            align_actions[align_menu.addAction("Center")] = "hcenter"
            align_actions[align_menu.addAction("Right")] = "right"
            align_menu.addSeparator()
            align_actions[align_menu.addAction("Top")] = "top"
            align_actions[align_menu.addAction("Middle")] = "vcenter"
            align_actions[align_menu.addAction("Bottom")] = "bottom"
            align_menu.addSeparator()
            align_actions[align_menu.addAction("Snap to grid")] = "grid"
            menu.addSeparator()

        style_actions = self._create_shape_style_actions(menu, item)
        if style_actions:
            menu.addSeparator()

        back1_act = menu.addAction("Send backward")
        front1_act = menu.addAction("Bring forward")
        menu.addSeparator()
        back_act = menu.addAction("Send to back")
        front_act = menu.addAction("Bring to front")

        action = menu.exec(event.globalPos())
        if not action:
            super().contextMenuEvent(event)
            return

        if action in align_actions:
            self._align_items(selected, align_actions[action])
        elif action is group_act:
            self._group_selected_items()
        elif action is ungroup_act:
            self._ungroup_selected_items()
        else:
            style_callback = style_actions.get(action)
            if style_callback:
                style_callback()
            elif action in (back1_act, front1_act, back_act, front_act):
                scene = self.scene()
                items = [
                    it
                    for it in scene.items()
                    if it.data(0) in SHAPES or isinstance(it, GroupItem)
                ]
                items.sort(key=lambda it: it.zValue())
                idx = items.index(item)
                if action == back1_act and idx > 0:
                    items[idx - 1], items[idx] = items[idx], items[idx - 1]
                elif action == front1_act and idx < len(items) - 1:
                    items[idx + 1], items[idx] = items[idx], items[idx + 1]
                elif action == back_act:
                    items.insert(0, items.pop(idx))
                elif action == front_act:
                    items.append(items.pop(idx))
                for z, it in enumerate(items):
                    it.setZValue(z)
            else:
                super().contextMenuEvent(event)
