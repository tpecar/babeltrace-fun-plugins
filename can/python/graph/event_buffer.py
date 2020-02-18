"""
Set of building blocks that store BT2 messages in a fast buffer, and display them in a Qt application with lazy loading.
"""

import numpy as np

from PyQt5.Qt import Qt, QAbstractTableModel, QAbstractItemModel, QModelIndex


class AppendableArray:
    """
    Appendable Array, implemented as a list of fixed size buffers.
    """
    __slots__ = ['_block_size', '_dtype', '_array', '_full_blocks', '_last_block_used']

    def __init__(self, block_size, event_dtype):
        self._block_size = block_size
        self._dtype = np.dtype(event_dtype)  # struct dtype of one element (row) in the table
        self._array = [np.empty(self._block_size, dtype=self._dtype)]
        self._full_blocks = 0       # Number of fully used blocks
        self._last_block_used = 0   # Number of saved events in the last block

    def __len__(self):
        return self._full_blocks * self._block_size + self._last_block_used

    def __getitem__(self, idx):
        if idx > len(self):
            raise IndexError

        return self._array[idx // self._block_size][idx % self._block_size]

    @property
    def dtype(self):
        return self._dtype

    def append(self, item):
        if self._last_block_used == self._block_size:
            new_block = np.empty(self._block_size, dtype=self._dtype)
            new_block[0] = item
            self._array.append(new_block)

            self._last_block_used = 1
            self._full_blocks += 1
        else:
            self._array[self._full_blocks][self._last_block_used] = item
            self._last_block_used += 1


class AppendableTableModel(QAbstractTableModel):
    """
    Table data model that uses AppendableArray for storing model data, for fast access during view redraws.
    It uses fetchMore mechanism for on-demand row loading.

    More info on
      https://doc.qt.io/qt-5/qabstracttablemodel.html
      https://sateeshkumarb.wordpress.com/2012/04/01/paginated-display-of-table-data-in-pyqt/
      PyQt5-5.xx.x.devX/examples/itemviews/fetchmore.py
      PyQt5-5.xx.x.devX/examples/itemviews/storageview.py
      PyQt5-5.xx.x.devX/examples/multimediawidgets/player.py
    """

    __slots__ = ['_array', '_data_headers', '_data_columnCount', '_data_rowCount']

    def __init__(self, block_size, dtype_struct, parent=None):
        super().__init__(parent)

        self._array = AppendableArray(block_size, dtype_struct)

        self._data_headers = [dtype_struct_member[0] for dtype_struct_member in dtype_struct]
        self._data_columnCount = len(self._data_headers)  # Displayed column count
        self._data_rowCount = 0  # Displayed row count

    def rowCount(self, parent=QModelIndex()):
        return self._data_rowCount

    def columnCount(self, parent):
        return self._data_columnCount

    def data(self, index, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and index.isValid() and self._array:
            # This is where we return data to be displayed
            return str(self._array[index.row()][index.column()])

        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal and section < len(self._data_headers):
                return self._data_headers[section]
        return None

    def canFetchMore(self, index):
        return self._data_rowCount < len(self._array)

    def fetchMore(self, index):
        itemsToFetch = len(self._array) - self._data_rowCount

        self.beginInsertRows(QModelIndex(), self._data_rowCount + 1, self._data_rowCount + itemsToFetch)
        self._data_rowCount += itemsToFetch
        self.endInsertRows()

    def append(self, item):
        self._array.append(item)

class Index():
    def __init__(self, idx):
        self.idx = idx


class AppendableTreeModel(QAbstractItemModel):
    """
    Tree data model that uses AppendableArray for storing model data, for fast access during view redraws.

    More info:
     PyQt5-5.14.2.devX/examples/itemviews/simpletreemodel/simpletreemodel.py
     PyQt5-5.14.2.devX/examples/itemviews/editabletreemodel/editabletreemodel.py
    """

    def __init__(self, block_size, dtype_struct, parent=None):
        super().__init__(parent)

        # TODO compare with a simple list implementation if such optimisations are even worth it

        # The root node is first entry, its children reference it with parent_idx = 0
        # The structure member names are used as column names
        #
        # One *big* assumption here is that the items are appended in a *depth-first*,
        #   so that a parent is directly followed by its children.
        #
        # parent_idx is the index of the parent node
        # child_idx is the index of this node from the prespective of its parent
        # num_children is the number of direct children
        # next_sibling is the index of the sibling - this essentially skips all children of the current node
        #
        self._array = AppendableArray(block_size,
            [
                ('parent_idx', np.uint32),
                ('child_idx', np.uint32),
                ('num_children', np.uint32),
                ('next_sibling', np.uint32)
            ] + dtype_struct
        )

        self._data_headers = [dtype_struct_member[0] for dtype_struct_member in dtype_struct]
        self._data_columnCount = len(self._data_headers)  # Displayed column count
        self._data_rowCount = 0  # Displayed row count

        # This is just a test
        self._array.append((0, 0, 4, 0, "Root Node", "Root Node Test 2"))
        self._array.append((0, 0, 0, 1, "Root CH1", "Test 2"))
        self._array.append((0, 1, 0, 1, "Root CH2", "Test 2"))
        self._array.append((0, 2, 2, 1, "Root CH3", "Test 2"))
        self._array.append((2, 0, 0, 1, "CH2 CH1", "Test 2"))
        self._array.append((2, 1, 0, 1, "CH2 CH2", "Test 2"))
        self._array.append((0, 3, 0, 1, "Root CH4", "Test 2 Root CH4"))

        # Workaround for python garbage collector, which nulls all effort done here
        self._index_obj = {}


    def rowCount(self, parent):
        # A common convention used in models that expose tree data structures is
        # that only items in the first column have children.
        if parent.column() > 0:
            return 0

        # In the index() method, we call self.createIndex(row, count, obj) with obj being the index of the item in
        # the _array. Do note that even indexes (int) are objects in Python, so internalPointer is a pointer to int obj.
        #
        # When the view initially accesses the model, it presents an invalid parent to ge the root node.
        #
        return self._array[parent.internalPointer()[0] if  parent.isValid() else 0][2] # 2 = num_children

    def columnCount(self, parent):
        return self._data_columnCount

    def data(self, index, role):
        if role == Qt.DisplayRole and index.isValid() and self._array:
            print(self._array[index.internalPointer()[0]][4 + index.column()])
            return self._array[index.internalPointer()[0]][4 + index.column()] # 4 = user specified dtype_struct start
        return None

    def flags(self, index):
        if index.isValid():
            return Qt.ItemIsEnabled | Qt.ItemIsSelectable
        return Qt.NoItemFlags

    def headerData(self, section, orientation, role):
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal and section < len(self._data_headers):
                return self._data_headers[section]
        return None

    def index(self, row, column, parent):
        if not self.hasIndex(row, column, parent):
            return QModelIndex()

        # Get current element if valid, otherwise root node (done by view when initially accessing the model)
        currentIdx = parent.internalPointer()[0] if parent.isValid() else 0
        parentItem = self._array[currentIdx]

        # This is a common special case, where the parent only has direct children - in this case we can directly
        # index the child
        if parentItem[2] + currentIdx == parentItem[3]:
            return self.createIndex(row, column, self._index(currentIdx + row))

        # If the parent's children have children of their own, we have to figure out the index of the 'row'-th sibling
        # of the first child.
        # This is by far the *slowest operation*, which is rather unfortunate for the use case
        else:
            currentIdx += 1 # Move to the first child of the parent
            for cur_row in range(row):
                currentIdx = self._array[currentIdx][3] # next_sibling

            return self.createIndex(row, column, self._index(currentIdx))

    def parent(self, index):
        if not index.isValid():
            return QModelIndex()

        currentItem = self._array[index.internalPointer()[0]]

        if currentItem[0] == 0: # parent_idx
            return QModelIndex()

        # row: the row of the parent (P) of the current node (N, N is child of P), with respect to its parent (P's parent)
        # column: 0
        # internalPointer: _array index of parent
        return self.createIndex(self._array[currentItem[0]][1], 0, currentItem[0])

    # This is a stupid workaround for a stupid issue of python deleting objects that are saved in qt context
    def _index(self, idx):
        if idx in self._index_obj:
            return self._index_obj[idx]
        else:
            self._index_obj[idx] = [idx]
            return self._index_obj[idx]
