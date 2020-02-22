"""
Set of building blocks that store BT2 messages in a fast buffer, and display them in a Qt application with lazy loading.
"""

import numpy as np

from PyQt5.Qt import Qt, QAbstractTableModel, QAbstractItemModel, QModelIndex


class AppendableTableModel(QAbstractTableModel):
    """
    Table model with fetchMore mechanism for on-demand row loading.

    More info
      https://doc.qt.io/qt-5/qabstracttablemodel.html
      https://sateeshkumarb.wordpress.com/2012/04/01/paginated-display-of-table-data-in-pyqt/
      PyQt5-5.14.2.devX/examples/itemviews/fetchmore.py
      PyQt5-5.14.2.devX/examples/itemviews/storageview.py
      PyQt5-5.14.2.devX/examples/multimediawidgets/player.py
    """

    def __init__(self, headers, parent=None):
        super().__init__(parent)

        self._table = []

        self._data_headers = headers
        self._data_columnCount = len(self._data_headers)  # Displayed column count
        self._data_rowCount = 0  # Displayed row count

    def rowCount(self, parent=QModelIndex()):
        return self._data_rowCount

    def columnCount(self, parent):
        return self._data_columnCount

    def data(self, index, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and index.isValid() and self._table:
            # This is where we return data to be displayed
            return str(self._table[index.row()][index.column()])

        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal and section < len(self._data_headers):
                return self._data_headers[section]
            if orientation == Qt.Vertical:
                return section
        return None

    def canFetchMore(self, index):
        return self._data_rowCount < len(self._table)

    def fetchMore(self, index):
        itemsToFetch = len(self._table) - self._data_rowCount

        self.beginInsertRows(QModelIndex(), self._data_rowCount + 1, self._data_rowCount + itemsToFetch)
        self._data_rowCount += itemsToFetch
        self.endInsertRows()

    def append(self, item_data):
        """
        Append item with provided item_data to end of table.
        :param item_data: table view columns
        :return: None
        """
        self._table.append(item_data)

        # If first element, notify view so that it starts updating
        if len(self._table) == 1:
            self.modelReset.emit()


class AppendableTreeModel(QAbstractItemModel):
    """
    Tree implemented as a linked TreeItem objects.

    More info
     PyQt5-5.14.2.devX/examples/itemviews/simpletreemodel/simpletreemodel.py
     PyQt5-5.14.2.devX/examples/itemviews/editabletreemodel/editabletreemodel.py
    """

    class TreeItem(object):
        """
        Single node in tree.
        """

        def __init__(self, data, parent=None):
            self.parentItem = parent
            self.itemData = data
            self.childItems = []

            self.index = {}
            self.parentIndex = None

        def indexReady(self):
            # View needs to query the model and generate QModelIndex objects for data columns, before we can notify
            # the view of item data change.
            return self.index and len(self.index) == len(self.itemData)

        def child(self, row):
            return self.childItems[row]

        def childCount(self):
            return len(self.childItems)

        def columnCount(self):
            return len(self.itemData)

        def data(self, column):
            try:
                return self.itemData[column]
            except IndexError:
                return None

        def parent(self):
            return self.parentItem

        def row(self):
            if self.parentItem:
                return self.parentItem.childItems.index(self)
            return 0

        def appendItem(self, item_data):
            """
            Append item with provided item_data as the last child of this node
            :param item_data: tree view columns
            :return: child item
            """
            item = type(self)(item_data, self)
            self.childItems.append(item)
            return item


    def __init__(self, rootItem_data, parent=None):
        super().__init__(parent)

        self.rootItem = type(self).TreeItem(rootItem_data)

    def rowCount(self, parent):
        if parent.column() > 0:
            return 0

        if not parent.isValid():
            parentItem = self.rootItem
        else:
            parentItem = parent.internalPointer()

        return parentItem.childCount()

    def columnCount(self, parent):
        if parent.isValid():
            return parent.internalPointer().columnCount()
        else:
            return self.rootItem.columnCount()

    def data(self, index, role):
        if not index.isValid():
            return None

        if role != Qt.DisplayRole:
            return None

        item = index.internalPointer()

        return item.data(index.column())

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags

        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def headerData(self, section, orientation, role):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.rootItem.data(section)

        return None

    def index(self, row, column, parent):
        if not self.hasIndex(row, column, parent):
            return QModelIndex()

        if not parent.isValid():
            parentItem = self.rootItem
        else:
            parentItem = parent.internalPointer()

        childItem = parentItem.child(row)
        if childItem:
            # The initial view query will create index objects
            # Do note that nodes should not be moved / deleted!
            if column not in childItem.index:
                childItem.index[column] = self.createIndex(row, column, childItem)

            return childItem.index[column]
        else:
            return QModelIndex()

    def parent(self, index):
        if not index.isValid():
            return QModelIndex()

        childItem = index.internalPointer()
        parentItem = childItem.parent()

        if parentItem == self.rootItem:
            return QModelIndex()

        if not childItem.parentIndex:
            childItem.parentIndex = self.createIndex(parentItem.row(), 0, parentItem)

        return childItem.parentIndex
