from qgis.PyQt.QtWidgets import QWidget, QVBoxLayout, QPushButton, QCheckBox, QLabel, QScrollArea, QDockWidget, QMessageBox, QAction
from qgis.core import (
    QgsProject, QgsFeature, QgsGeometry, QgsSpatialIndex, QgsPointXY,
    QgsVectorLayer, QgsField
)
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QIcon
import os
from collections import defaultdict
from qgis.core import QgsWkbTypes, QgsPointXY, QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry, QgsField
from qgis.utils import iface

from PyQt5.QtWidgets import QMessageBox
class CleanChainPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.dock = None
        self.action = None

    def initGui(self):
        self.dock = QDockWidget("Έλεγχος ψευδοκόμβων", self.iface.mainWindow())
        self.widget = QWidget()
        layout = QVBoxLayout()

        self.scroll = QScrollArea()
        self.field_widget = QWidget()
        self.field_layout = QVBoxLayout()
        self.field_checks = []

        self.field_widget.setLayout(self.field_layout)
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.field_widget)

        self.topo_button = QPushButton("Run Topology Checker")
        self.topo_button.clicked.connect(self.run_topology_checker)
        layout.addWidget(self.topo_button)
        self.topo_checkbox = QCheckBox("Έλεγχος στα επιλεγμένα")
        layout.addWidget(self.topo_checkbox)



        self.checkbox = QCheckBox("Έλεγχος μόνο στα επιλεγμένα")
        self.run_button = QPushButton("Εκτέλεση ελέγχου")

        layout.addWidget(QLabel("Επιλέξτε τα πεδία που δικαιολογούν το σπάσιμο (split) μιας γραμμής."))
        layout.addWidget(QLabel("Αν οι τιμές διαφέρουν σε κάποιο από αυτά, το σημείο δεν θεωρείται ψευδοκόμβος:"))
        layout.addWidget(self.scroll)

        self.clear_button = QPushButton("Καθαρισμός Επιλογών")
        self.clear_button.clicked.connect(self.clear_field_checks)
        layout.addWidget(self.clear_button)

        layout.addWidget(self.checkbox)
        layout.addWidget(self.run_button)

        self.widget.setLayout(layout)
        self.dock.setWidget(self.widget)
        self.iface.addDockWidget(0x1, self.dock)

        self.run_button.clicked.connect(self.run_analysis)
        self.iface.currentLayerChanged.connect(self.populate_fields)
        self.populate_fields()

        icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
        self.action = QAction(QIcon(icon_path), "Έλεγχος ψευδοκόμβων", self.iface.mainWindow())
        self.action.triggered.connect(lambda: self.dock.setVisible(True))
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("Έλεγχος ψευδοκόμβων", self.action)

    def unload(self):
        if self.dock:
            self.iface.removeDockWidget(self.dock)
            self.dock = None
        if self.action:
            self.iface.removeToolBarIcon(self.action)
            self.iface.removePluginMenu("Έλεγχος ψευδοκόμβων", self.action)
            self.action = None

    def populate_fields(self):
        layer = self.iface.activeLayer()
        if not layer or not layer.isValid() or layer.type() != layer.VectorLayer:
            return

        self.field_checks.clear()

        prev_states = {cb.text(): cb.isChecked() for cb in self.field_checks}

        while self.field_layout.count():
            child = self.field_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        for field in layer.fields():
            check = QCheckBox(field.name())
            if field.name() in ['check', 'test']:
                check.setChecked(True)
            self.field_checks.append(check)
            self.field_layout.addWidget(check)

    def run_analysis(self):
        layer = self.iface.activeLayer()
        if not layer or layer.geometryType() != 1:
            QMessageBox.warning(self.widget, "Σφάλμα", "Παρακαλώ επιλέξτε γραμμικό επίπεδο")
            return

        selected_fields = [cb.text() for cb in self.field_checks if cb.isChecked()]
        if not selected_fields:
            QMessageBox.warning(self.widget, "Σφάλμα", "Παρακαλώ επιλέξτε τουλάχιστον ένα πεδίο.")
            return

        only_selected = self.checkbox.isChecked()
        features = layer.selectedFeatures() if only_selected else list(layer.getFeatures())

        if not features:
            QMessageBox.warning(self.widget, "Σφάλμα", "Δεν υπάρχουν επιλεγμένα στοιχεία.")
            return

        spatial_index = QgsSpatialIndex()
        for feat in features:
            spatial_index.insertFeature(feat)
        all_features = {f.id(): f for f in features}
        visited = set()
        valid_ids = set()

        def get_start_end_points(geom):
            if geom.isMultipart():
                lines = geom.asMultiPolyline()
                points = []
                for line in lines:
                    if len(line) >= 2:
                        points.append(QgsPointXY(line[0]))
                        points.append(QgsPointXY(line[-1]))
                return points
            else:
                line = geom.asPolyline()
                if not line or len(line) < 2:
                    return []
                return [QgsPointXY(line[0]), QgsPointXY(line[-1])]

        endpoint_map = defaultdict(set)
        for feat in all_features.values():
            for pt in get_start_end_points(feat.geometry()):
                key = (round(pt.x(), 6), round(pt.y(), 6))
                endpoint_map[key].add(feat.id())

        for feat in all_features.values():
            if feat.id() in visited:
                continue

            group = [feat]
            queue = [feat]
            visited.add(feat.id())
            attrs = [feat[field] for field in selected_fields]

            while queue:
                current = queue.pop()
                current_geom = current.geometry()
                current_points = get_start_end_points(current_geom)

                nearby_ids = spatial_index.intersects(current_geom.boundingBox())
                for nearby_id in nearby_ids:
                    if nearby_id in visited:
                        continue
                    neighbor = all_features[nearby_id]
                    if neighbor.geometry().touches(current_geom):
                        neighbor_attrs = [neighbor[field] for field in selected_fields]
                        if neighbor_attrs != attrs:
                            continue

                        neighbor_points = get_start_end_points(neighbor.geometry())
                        shared = set(current_points) & set(neighbor_points)

                        if len(shared) == 1:
                            shared_point = next(iter(shared))
                            key = (round(shared_point.x(), 6), round(shared_point.y(), 6))
                            if len(endpoint_map[key]) > 2:
                                continue

                            queue.append(neighbor)
                            group.append(neighbor)
                            visited.add(neighbor.id())

            endpoint_counts = defaultdict(int)
            for f in group:
                for pt in get_start_end_points(f.geometry()):
                    key = (round(pt.x(), 6), round(pt.y(), 6))
                    endpoint_counts[key] += 1

            degree_one = sum(1 for v in endpoint_counts.values() if v == 1)
            max_endpoint = max(endpoint_counts.values())

            valid_chain = True
            for f in group:
                count = 0
                geom = f.geometry()
                for other in group:
                    if f.id() != other.id() and geom.touches(other.geometry()):
                        count += 1
                if count > 2:
                    valid_chain = False
                    break

            if len(group) > 1 and degree_one == 2 and max_endpoint == 2 and valid_chain:
                valid_ids.update([f.id() for f in group])

        point_layer = QgsVectorLayer("Point?crs=" + layer.crs().authid(), "clean_chain_points", "memory")
        pr = point_layer.dataProvider()
        pr.addAttributes([QgsField("fid", QVariant.Int)])
        point_layer.updateFields()

        for fid in valid_ids:
            feat = all_features[fid]
            for pt in get_start_end_points(feat.geometry()):
                new_feat = QgsFeature()
                new_feat.setGeometry(QgsGeometry.fromPointXY(pt))
                new_feat.setAttributes([fid])
                pr.addFeature(new_feat)

        QgsProject.instance().addMapLayer(point_layer)
        layer.selectByIds(list(valid_ids))




    def run_topology_checker(self):
        try:
            layer = iface.activeLayer()
            if not layer or layer.geometryType() != QgsWkbTypes.LineGeometry:
                raise Exception("This layer is not a valid Line layer.")

            def point_key(pt, precision=6):
                return (round(pt.x(), precision), round(pt.y(), precision))

            endpoint_index = defaultdict(list)
            for feat in (layer.selectedFeatures() if self.topo_checkbox.isChecked() else layer.getFeatures()):
                geom = feat.geometry()
                lines = geom.asMultiPolyline() if geom.isMultipart() else [geom.asPolyline()]
                for line in lines:
                    if len(line) >= 2:
                        start_pt = point_key(line[0])
                        end_pt = point_key(line[-1])
                        endpoint_index[start_pt].append(feat.id())
                        endpoint_index[end_pt].append(feat.id())

            snapped_points = []
            for pt_key, ids in endpoint_index.items():
                if len(ids) == 2 and ids[0] != ids[1]:
                    snapped_points.append(QgsPointXY(*pt_key))

            mem_layer = QgsVectorLayer("Point?crs=" + layer.crs().authid(), "Unmerged Snap Points", "memory")
            prov = mem_layer.dataProvider()
            prov.addAttributes([QgsField("id", QVariant.Int)])
            mem_layer.updateFields()

            features = []
            for i, pt in enumerate(snapped_points):
                f = QgsFeature()
                f.setGeometry(QgsGeometry.fromPointXY(pt))
                f.setAttributes([i])
                features.append(f)
            prov.addFeatures(features)
            mem_layer.updateExtents()
            QgsProject.instance().addMapLayer(mem_layer)

            QMessageBox.information(self.iface.mainWindow(), "Topology Checker", f"Found {len(snapped_points)} snapped endpoints.")
        except Exception as e:
            QMessageBox.critical(self.iface.mainWindow(), "Error", str(e))


    def clear_field_checks(self):
        for cb in self.field_checks:
            cb.setChecked(False)
