"""@package AlchemyProvider
Documentation for this module.

More details.
"""


import os
import re
import logging
from scipy.stats.mstats_basic import variation
import sqlalchemy
import sqlalchemy.orm
from sqlalchemy import desc

from Model import Directory, TypeTable, TypeTableColumn, ConstantSet, Assignment, RunRange, Variation


import posixpath

log = logging.getLogger("ccdb.AlchemyProvider")



class AlchemyProvider(object):
    """
    CCDB data provider that uses SQLAlchemy for accessing databases
    """

    def __init__(self):
        self._is_connected = False
        self._are_dirs_loaded = False
        self.root_dir = Directory()
        self.root_dir.path = '/'
        self.root_dir.name = ''
        self.root_dir.id = 0
        self.path_name_regex = re.compile('^[\w\-_]+$', re.IGNORECASE)


#----------------------------------------------------------------------------------------
#	C O N N E C T I O N
#----------------------------------------------------------------------------------------

    ##
    # @brief Connects to database using connection string
    #
    # Connects to database using connection string
    # connection string might be in form:
    # mysql://<username>:<password>@<mysql.address>:<port> <database>
    #
    # @param connectionString: str "mysql://<username>:<password>@<mysql.address>:<port> <database>"
    # @return True if connected
    def connect(self, connection_string = ""):
        """
        :param connection_string: connection string
        :type connection_string: str
        """

        if connection_string == "":
            if "CCDB_CONNECTION" in os.environ:
                connection_string = os.environ["CCDB_CONNECTION"]
            else:
                raise ValueError("No CCDB_CONNECTION environment variable is set. No connection string to connect")

        self.engine = sqlalchemy.create_engine(connection_string)
        Session = sqlalchemy.orm.sessionmaker(bind=self.engine)
        self.session = Session()
        self._is_connected = True

        #since it is a new connection we need to rebuild directories
        self._are_dirs_loaded = False

    #------------------------------------------------
    # Closes connection to data
    #------------------------------------------------
    def disconnect(self):
        """Closes connection to database"""
        #TODO close pool logic???
        self._is_connected = False
        self.session.close()


    #-------------------------------------------------
    # indicates ether the connection is open or not
    #-------------------------------------------------
    @property
    def is_connected(self):
        """
        indicates ether the connection is open or not

        :return: bool True if connection is opened
        :rtype: bool
        """
        return self._is_connected




    #------------------------------------------------
    # Connection string that was used
    #------------------------------------------------
    @property
    def connection_string(self):
        """
        Connection string that was used on last connect()

        :return: connection string
        :rtype: str
        """
        return self._connection_string


#----------------------------------------------------------------------------------------
#	D I R E C T O R Y   M A N G E M E N T
#----------------------------------------------------------------------------------------


    #------------------------------------------------
    # Gets directory by its full path
    #------------------------------------------------
    def get_directory(self, path):
        """
        Gets directory by its full path

        :param path: Full path of the directory
        :type path: str
        :return: Directory object if directory exists, NULL otherwise
        :rtype: Directory
        """
        if not self._are_dirs_loaded: self._load_dirs()

        #we don't have this directory
        if not path in self.dirs_by_path.keys():
            raise KeyError("Can't find the directory with path '{0}'".format(path))

        return self.dirs_by_path[path]


    #------------------------------------------------
    # return reference to root directory
    #------------------------------------------------
    def get_root_directory(self):
        """
        return reference to root directory

        @warning User should not delete this object

        :return:reference to root directory
        :rtype: Directory
        """
        if not self._are_dirs_loaded: self._load_dirs()
        return self.root_dir


    #------------------------------------------------
    # Searches directories that matches the pattern
    #------------------------------------------------
    def search_directories(self, searchPattern, parentPath="", limit=0, offset=0):
        """
        Searches directories that matches the pattern
        inside parent directory with path parentPath
        or globally through all type tables if parentPath is empty
        The pattern might contain wildcard characters:
        '*' - any character sequence
        '?' - any single character

        :param searchPattern: Pattern to search. May have wildcards '*' and '?'
        :type searchPattern: str

        :param parentPath: Parent path. If empty search through all directories
        :type parentPath: str

        :param limit: number of records to select. 0 means select all records
        :type limit: int

        :param offset: record number to start with
        :type offset: int

        :return: Directories to find
        :rtype: [] of Directory
        """
        if not self._are_dirs_loaded: self._load_dirs()

        searchPattern = searchPattern.replace("_", "\\_").replace("*","%").replace("?","_")

        query = self.session.query(Directory).filter(Directory.name.like(searchPattern, escape="\\"))

        if parentPath !="":
            parent_dir = self.dirs_by_path[parentPath]
            query = query.filter(Directory.parent_id == parent_dir.id)

        if limit !=0: query = query.limit(limit)
        if offset!=0: query = query.offset(offset)

        result = query.all()

        return result


    #------------------------------------------------
    # Creates directory using parent path
    #------------------------------------------------
    def create_directory(self, new_dir_name, parent_dir_or_path, comment=""):
        """
        Creates directory using parent with parentDirFullPath

        :param new_dir_name: Name of the directory. May contain only A-Z, a-z,0-9, _, -,
        :type new_dir_name:str
        :param parent_full_path: Path of the parent directory
        :type parent_full_path: str
        :param comment: comment on this dir. Might be None
        :type comment:
        :return: new created Directory
        :rtype: Directory
        """
        if not self._are_dirs_loaded: self._load_dirs()

        #get parent directory
        if isinstance(parent_dir_or_path, str):
            parent_dir = self.dirs_by_path[parent_dir_or_path]
        else:
            assert (isinstance(parent_dir_or_path, Directory))
            parent_dir = parent_dir_or_path

        #check if no such directory exists
        new_full_path = posixpath.join(parent_dir.path, new_dir_name)
        if new_full_path in self.dirs_by_path.keys():
            raise ValueError("The directory with path '{0}' already exist".format(new_full_path))

        #create the directory
        dir = Directory()
        dir.name = new_dir_name
        if comment!="": dir.comment = comment
        else: dir.comment = None
        dir.parent_dir = parent_dir
        dir.parent_id = parent_dir.id
        parent_dir.sub_dirs.append(dir)

        #add to database
        self.session.add(dir)
        self.session.commit()

        #refresh directory structure
        self._load_dirs()

        return dir


    ## @brief Updates directory
    #
    # @warning in current realization, if operation succeeded
    # the directories structure will be rebuilded. This mean that
    # (!) all previous pointers to DDirectory objects except Root Directory
    # will become deleted => unusable
    #
    # @param [in] ccdb.Directory object - Directory to update
    # @return bool True if success
    #/
    def update_directory(self, directory):
        "Updates directory"
        if not self._are_dirs_loaded: self._load_dirs()
        self.session.commit()

        #refresh directory structure
        self._load_dirs()


    #------------------------------------------------
    # Deletes directory using path or Directory obj
    #------------------------------------------------
    def delete_directory(self, dir_or_path):
        """
        Deletes directory using parent path or Directory object

        :param dir_or_path:parent path or Directory object
        :type dir_or_path: str or Directory
        :return: None
        """

        if not self._are_dirs_loaded: self._load_dirs()

        #check the type
        if isinstance(dir_or_path, str):
            directory = self.dirs_by_path[dir_or_path]
        else:
            assert(isinstance(dir_or_path, Directory))
            directory = dir_or_path

        if len(directory.sub_dirs) != 0 or len(directory.type_tables) != 0:
            raise ValueError("Directory '{0}' contains {1} subdirectories and {2} tables."+\
                             "Impossible to delete directory which contains another directories or tables"\
                            .format(directory.path, len(directory.sub_dirs),  len(directory.type_tables)))

        self.session.delete(directory)
        self.session.commit()

        #refresh directory structure
        self._load_dirs()


    #------------------------------------------------
    # Load all directories
    #------------------------------------------------
    def _load_dirs(self):
        self.dirs_by_id = self._get_dirs_by_id_dic(self.session.query(Directory).all())
        self.dirs_by_path = self._structure_dirs(self.dirs_by_id)
        self._are_dirs_loaded = True

    #------------------------------------------------
    # Structure directories by hierarchy
    #------------------------------------------------
    def _structure_dirs(self, dirs):
        """
        :type dirs: {} dictionary with dir.id as a key
        """
        assert(isinstance(dirs,type({})))

        #clear the full path dictionary
        dirsByFullPath = {self.root_dir.path: self.root_dir}

        #clear subdirectories to append them from the beginning in the next step
        for dir in dirs.values(): dir.sub_dirs = []

        #begin loop through the directories
        for dir in dirs.values():
            assert (isinstance(dir, Directory))

            parent_dir = self.root_dir

            # and check if it have parent directory
            if dir.parent_id >0:
                #this directory must have a parent! so now search it
                parent_dir = dirs[dir.parent_id]

            parent_dir.sub_dirs.append(dir)
            dir.path = posixpath.join(parent_dir.path, dir.name)
            dir.parent_dir = parent_dir
            dirsByFullPath[dir.path] = dir

        return dirsByFullPath
    #end of structure_dirs()


    #------------------------------------------------
    # create dictionary by directory id
    #------------------------------------------------
    def _get_dirs_by_id_dic(self, dirs):
        result = {}
        for dir in dirs:
            assert(isinstance(dir, Directory))
            result[dir.id]=dir

        return result




#----------------------------------------------------------------------------------------
#	C O N S T A N T   T Y P E   T A B L E
#----------------------------------------------------------------------------------------


    #------------------------------------------------
    # Gets TypeTable from the DB by absolute path
    #------------------------------------------------
    def get_type_table(self, exact_path):
        """
        Gets TypeTable from the DB by absolute path
        :param exact_path: absolute path of the type table
        :type exact_path: str
        :param load_columns:
        :type load_columns: bool
        :return: TypeTable that matches this path
        :rtype: TypeTable
        """
        if not self._are_dirs_loaded: self._load_dirs()

        parent_dir_path = posixpath.dirname(exact_path)
        table_name = posixpath.basename(exact_path)
        parent_dir = self.dirs_by_path[parent_dir_path]

        return self.session.query(TypeTable).filter(TypeTable.name == table_name, TypeTable.parent_dir_id == parent_dir.id).one()


    #------------------------------------------------
    # Get all tables in the directory
    #------------------------------------------------
    def get_type_tables(self, dir_obj_or_path):
        """
        Get all tables in the directory

        :param dir_obj_or_path: directory or path to directory where to look
        :type dir_obj_or_path: str or Directory
        :param loadColumns:
        :return: [] of TypeTables for the directory
        :rtype: [] of TypeTable
        """
        if not self._are_dirs_loaded: self._load_dirs()

        if isinstance(dir_obj_or_path, str):
            parent_dir = self.dirs_by_path[dir_obj_or_path]
        else:
            assert isinstance(dir_obj_or_path, Directory)
            parent_dir = dir_obj_or_path

        return self.session.query(TypeTable).filter(TypeTable.parent_dir_id == parent_dir.id).all()


    #------------------------------------------------
    # Searches for type tables that matches the patten
    #------------------------------------------------
    def search_type_tables(self, pattern, dir_obj_or_path=None, limit=0, offset=0):
        """
        Searches for type tables that matches the patten

        inside parent directory with path @see parentPath
        or globally through all type tables if parentPath is empty
        The pattern might contain
        '*' - any character sequence
        '?' - any single character

        :param pattern: Search pattern. May contain with wildcard '*' and '?' symbols
        :type pattern: str

        :param dir_obj_or_path: parent Directory object, full path of parent directory or None if
        :type dir_obj_or_path: str, Directory, None

        :param limit: number of records to select. 0 means select all records
        :type limit: int

        :param offset: record number to start with
        :type offset: int

        :return: found TypeTables
        :rtype: []
        """

        #prepare search pattern for SQL
        pattern = pattern.replace("_", "\\_").replace("*","%").replace("?","_")

        #initial query
        query = self.session.query(TypeTable).filter(TypeTable.name.like(pattern, escape="\\"))

        #does parent directory specified?
        parent_dir = None
        if dir_obj_or_path != None:
            if not self._are_dirs_loaded: self._load_dirs()

            if isinstance(dir_obj_or_path, str) and dir_obj_or_path != "":
                parent_dir = self.dirs_by_path[dir_obj_or_path]
            else:
                assert isinstance(dir_obj_or_path, Directory)
                parent_dir = dir_obj_or_path

        #add parent directory to query
        if parent_dir != None:
            query.filter(TypeTable.dir_id == parent_dir.id)

        #add limits to query
        if limit !=0: query = query.limit(limit)
        if offset!=0: query = query.offset(offset)

        #execute and return
        return query.all()


    #------------------------------------------------
    # Counts number of type tables for a given directory
    #------------------------------------------------
    def count_type_tables(self, dir_obj_or_path):
        """
        Counts number of type tables for a given directory

        :param dir_obj_or_path: parent directory or full path of parent directory
        :type dir_obj_or_path: str or Directory

        :return: number of type tables in a directory
        :rtype: int
        """

        if not self._are_dirs_loaded: self._load_dirs()

        if isinstance(dir_obj_or_path, str):
            parent_dir = self.dirs_by_path[dir_obj_or_path]
        else:
            assert isinstance(dir_obj_or_path, Directory)
            parent_dir = dir_obj_or_path

        return self.session.query(TypeTable).filter(TypeTable.parent_dir_id == parent_dir.id).count()


    ## @brief Creates constant table in database
    #
    # Creates  constants type table in database and returns reference to
    # created table if operation is succeeded (NULL otherwise)
    #
    # The map "columns" should contains <"name", "type"> string pairs where:
    #  -- "name" is the name of the column.
    #      Should have the same naming convetions
    #      as names of directories and type tables  @see ValidateName()
    #  -- "type" is the type of the column
    #     might be: int, uint, long, ulong, double, bool, string
    #     other values will lead to "double" type to be used.
    #     @see ccdb::ConstantsTypeColumn::StringToType
    #     Thus <"px", "">, <"py", ""> will create two double typed columns
    #
    # @param [in] name			name of the new constants type table
    # @param [in] parentPath   parent directory path
    # @param [in] rowsNumber  Number of rows
    # @param [in] columns     a map fo "name", "type" pairs
    # @param [in] comments		description for this type table
    # @return NULL if failed, pointer to created object otherwise
    #/
    #------------------------------------------------
    #------------------------------------------------
    def create_type_table(self, name, dir_obj_or_path, rowsNumber, columns, comments =""):
        "Creates constant table in database"
        #return self._provider.CreateConstantsTypeTable(name, parentPath, rowsNumber, columns, comments)

        if not self._are_dirs_loaded: self._load_dirs()

        if isinstance(dir_obj_or_path, str):
            parent_dir = self.dirs_by_path[dir_obj_or_path]
        else:
            assert isinstance(dir_obj_or_path, Directory)
            parent_dir = dir_obj_or_path

        table = TypeTable()
        table.name = name
        table.comment = comments
        table.rows_count = rowsNumber
        table.parent_dir = parent_dir
        table.parent_dir_id = parent_dir.id

        for i, key in enumerate(columns):
            column = TypeTableColumn()
            column.name = columns[key]
            column.order = i
            table.columns.append(column)

        self.session.add(table)
        self.session.commit()

        return self._provider.CreateConstantsTypeTable(table)


    #------------------------------------------------
    # Uptades constant table in database
    #------------------------------------------------
    def update_type_table(self, type_table):
        self.session.commit()


    #------------------------------------------------
    # Deletes constant type table
    #------------------------------------------------
    def delete_type_table(self, type_table):
        """
        @brief Deletes constant type table

        Deletes constant type table.
        The type table will not be deleted if any assignment for this table exists
        Used should delete assignments first and only than delete the type table.

        :param type_table:   table table info
        :type type_table: TypeTable
        """
        assert isinstance(type_table, TypeTable)

        data_count = self.session.query(ConstantSet).filter(ConstantSet.type_table_id == type_table.id).count()
        if data_count>0:
            message = "Can't delete type table that has data assigned to it."\
                      + "The type table '{0}' with id '{1}'. It has {2} data sets which reference it."\
                      + "Please, delete the data first".format(type_table.path, type_table.id, data_count)
            raise ValueError(message)

        self.session.delete(type_table)
        self.session.commit()


#----------------------------------------------------------------------------------------
#	R U N   R A N G E S
#----------------------------------------------------------------------------------------


    #------------------------------------------------
    # GetRun Range from db by name or max and min run
    #------------------------------------------------
    def get_run_range(self, min_run, max_run, name=""):
        if name!="":
            return self.session.query(RunRange).filter(RunRange.name == name).one()

        return self.session.query(RunRange).filter(RunRange.min == min_run).filter(RunRange.max == max_run).one()



    #------------------------------------------------
    # GetRun Range from db by name
    #------------------------------------------------
    def get_named_run_range(self, name):
        """
        Get named run range from db

        :param name:
        :return:
        """
        return self.session.query(RunRange).filter(RunRange.name == name).one()


    #------------------------------------------------
    # Gets run range from DB Or Creates RunRange in DB
    #------------------------------------------------
    #noinspection PyBroadException
    def get_or_create_run_range(self, min_run, max_run, name = "", comment = ""):
        """
        Gets run range from DB Or Creates RunRange in DB

        :param min_run: min run
        :param max_run: max run
        :param name: name
        :param comment: comment in case we will have to create a new run range
        :return: RunRange object
        :rtype: RunRange
        """

        try:
            run_range = self.get_run_range(min_run, max_run, name)
            return run_range
        except:
            pass

        #if we here we was unable to find a run range
        run_range = RunRange()
        run_range.min = min_run
        run_range.max = max_run
        run_range.name = name
        run_range.comment = comment

        self.session.add(run_range)
        self.session.commit()
        return run_range


    #------------------------------------------------
    # Updates run range
    #------------------------------------------------
    def update_run_range(self, run_range):
        """
        Updates run range

        :param run_range: RunRange to update
        """

        self.session.commit()


    #------------------------------------------------
    # Deletes run range
    #------------------------------------------------
    def delete_run_range(self, run_range):
        """
        Deletes run range

        :param run_range_obj: RunRange object to delete
        :return: None
        """
        data_count = self.session.query(Assignment).filter(Assignment.run_range_id == run_range.id).count()
        if data_count>0:
            message = "Can't delete run range that has data assigned to it."\
                      + "The run range with id '{0}', name '{2}' [{3} - {4}] has {5} data sets which reference it."\
                      + "Please, delete the data first".format(run_range.id, run_range.name, run_range.min, run_range.max, data_count)
            raise ValueError(message)

        self.session.delete(run_range)
        self.session.commit()

#----------------------------------------------------------------------------------------
#	V A R I A T I O N S
#----------------------------------------------------------------------------------------


    #------------------------------------------------
    # Get variation by name
    #------------------------------------------------
    def get_variation(self, name):
        """
        Get variation by name

        :param name: Variation name
        :return: Variation object
        :rtype: Variation
        """
        return self.session.query(Variation).filter(Variation.name == name).one()


    #------------------------------------------------
    # Searches all variations associated with this type table
    #------------------------------------------------
    def get_variations(self, table_or_path, run = 0, limit = 0, offset = 0):
        """
        Searches all variations associated with this type table

        :param table_or_path: table table to search run ranges in
        :param run: specified run to search for, if run<0 searches for all run ranges
        :param limit: how many records to take. 0 - take all records
        :param offset: offset of first record to take.
        :return: list of variations
        :rtype: [Variation]
        """
        table = None
        if isinstance(table_or_path, str):
            table = self.get_type_table(table_or_path)
        else:
            assert isinstance(table_or_path, TypeTable)
            table = table_or_path
        if not table: return []

        query = self.session.query(Variation)\
                .join(Assignment).join(ConstantSet).join(TypeTable).join(RunRange)\
                .filter(TypeTable.id == table.id)
        if run>=0: query = query.filter(RunRange.min<=run).filter(RunRange.max>=run)
        if limit>0: query = query.limit(limit)
        if offset>0: query = query.offset(offset)
        return query.all()




    #----------------------.--------------------------
    # Create variation by name
    #------------------------------------------------
    def create_variation(self, name, comment=""):
        """
        Create variation by name

        :param name: Name of the variation
        :param comment: Comment for the variation

        :return: new created variation
        :rtype: Variation
        """
        variation = Variation()

        if self.session.query(Variation).filter(Variation.name == name).count() > 0:
            raise ValueError("Cannot create a new variation with name {0}. Variation with that name already exists".format(name))

        variation.comment = comment
        variation.name = name
        self.session.add(variation)
        self.session.commit()
        return variation


    ## @brief Update variation
    #
    # Function updates:
    # variation comments
    # variation name if there is no variations with this name
    #
    # @param   [in]  variation to update
    # @return true if success
    #/
    #------------------------------------------------
    #------------------------------------------------
    def update_variation(self, variation):
        self.session.commit()


    ## @brief Delete variation
    #
    # Variation will be deleted only
    # if there is no assignments for this variation
    # @param    [in] variation to delete
    # @return   bool
    #/
    #------------------------------------------------
    #------------------------------------------------
    def delete_variation(self, variation):
        assert isinstance(variation, Variation)

        data_count = self.session.query(Assignment).filter(Assignment.variation_id == variation.id).count()
        if data_count>0:
            message = "Can't delete variation that has data assigned to it."\
                      + "The variation '{0}' with id '{1} has {2} data sets which reference it."\
                      + "Please, delete the data first".format(variation.name, variation.id, data_count)
            raise ValueError(message)

        self.session.delete(variation)
        self.session.commit()

#----------------------------------------------------------------------------------------
#	A S S I G N M E N T S
#----------------------------------------------------------------------------------------


    ## @brief
    #
    # @param     int run
    # @param     path to constant path
    # @return NULL if no assignment is found or error
    #/
    #------------------------------------------------
    # Get last Assignment with all related objects
    #------------------------------------------------
    def get_assignment(self, run, path_or_table, variation):

        if isinstance(path_or_table, str):
            table = self.get_type_table(path_or_table)
        else:
            assert isinstance(path_or_table, TypeTable)
            table = path_or_table

        if isinstance(variation, str):
            variation_name = variation
        else:
            assert isinstance(variation, Variation)
            variation_name = variation.name

        query = self.session.query(Assignment)\
                .join(ConstantSet).join(TypeTable).join(RunRange).join(Variation)\
                .filter(Variation.name == variation_name)\
                .filter(TypeTable.id==table.id)\
                .filter(RunRange.min<=1000).filter(RunRange.max>=1000)\
                .order_by(desc(Assignment.id)).limit(1).one()


    ## @brief Creates Assignment using related object
    #
    # @warning since composing a "NEW" DAssignment is complex operation
    #          it is suggested to use other reloads of this function for users
    #          for creating "new" assignments.
    #          This function is not set as "protected" only to provide easy "copy" operations
    #
    # This function assumes that all needed data is already contained in assignment
    # object. Including correct type table and data blob.
    #
    # The function is powerful to copy assignment. For example from one variation to another.
    #
    # The function changes DAssignment object by setting Id and DataVaultId by new values
    #
    # @param    DAssignment * assignment
    # @return   DAssignment* adjusted with Id-s of objects and etc
    #/
    #------------------------------------------------
    # Creates Assignment using related object
    #------------------------------------------------
    def copy_assignment(self, asssignment):
        return self._provider.CreateAssignment(assignment)


    ## @brief Creates Assignment using related object
    #
    # Creates Assignment using related object.
    #
    # Validation:
    # If no such run range found, the new will be created (with no name)
    # No action will be done (and NULL will be returned):
    # -- If no type table with such path exists
    # -- If data is inconsistent with columns number and rows number
    # -- If no variation with such name found
    #
    # @brief
    # @param data  		by rows and columns
    # @param runMin		run range minimum
    # @param runMax     run range maximum
    # @param variationName	name of variation
    # @param comments   comments
    # @return NULL if failed, DAssignment reference if success
    #/
    #------------------------------------------------
    #------------------------------------------------
    def create_assignment(self, data, path, min_run, max_run, variation, comment):
        table = self.get_type_table(path);
        if not table:
            log.warning("Table : " + path + " - was not found. ")
            log.debug(self, data, path, min_run, max_run, variation, comment)
            return None

        assert isinstance(table, ccdb.ConstantsTypeTable)

        rows = None

        #maybe it is a dom?
        if isinstance(data, ccdb.TextFileDOM):
            rows = data.rows
        else:
            #it should be list than...
            rows = data

        #finally checking data type and that there is at least one row and column
        if (not isinstance(rows, list)) or\
           (not len(rows)) or\
           (not isinstance(rows[0], list)) or\
           (not len(rows[0])):
            log.warning("Data type is wrong in python function")
            return None

        #Create StringVectorVector for C++ wrapped function
        rows_vector = ccdb.StringVectorVector()
        for row in rows:
            cells_vector = ccdb.StringVector()
            for cell in row:
                if isinstance(cell, str):
                    cells_vector.push_back(cell)
                else:
                    cells_vector.push_back(repr(cell))
            rows_vector.push_back(cells_vector)
        print "rows " +repr(rows_vector.size())
        #do the job

        return self._provider.CreateAssignment(rows_vector, path, min_run, max_run, variation, comment)


    ## @brief Creates Assignment using related object
    #
    # Creates Assignment using related object.
    #
    # Validation:
    # If no such run range found, the new will be created (with no name)
    # No action will be done (and false will be returned):
    # -- If no type table with such path exists
    # -- If data is inconsistant with columns number and rows number
    # -- If no variation with such name found
    #
    # @brief
    # @param data  		by rows and columns
    # @param runRangeName
    # @param variation	name of vaiation
    # @param comments   comments
    # @return NULL if failed, DAssignment reference if success
    #/
    #virtual DAssignment* CreateAssignment(const vector<vector<string> > &data, const string& path, const string& runRangeName, const string& variationName, const string& comments);


    ##
    # @brief Get assigments for particular run
    #
    # returns vector of assignments
    # Variation: if variation is not empty string the assignments for specified variation will be returned
    #            otherwise all variations will be accepted
    #
    # Date: if date is not 0, assignments which are earlier than this date will be returned
    #       otherwise returned assignments will be not filtered by date
    #
    # Paging: paging could be done with  @see take ans @see startWith
    #         take=0, startWith=0 means select all records;
    #
    #
    # @param [in]  path
    # @param [in]  run
    # @param [in]  variation
    # @param [in]  date
    # @param [in]  take
    # @param [in]  startWith
    # @return assingments
    #/
    #------------------------------------------------
    #------------------------------------------------
    def get_assignments(self, path, run, variation = "default", unix_time_stamp =0, take=0, start_with=0):
        result = self._provider.GetAssignments(path, run, variation, unix_time_stamp, take, start_with)
        return [asg for asg in result]


    ##
    # @brief Get assigments for particular run
    #
    # returns vector of assignments
    # Variation: if variation is not emty string the assignments for specified variation will be returned
    #            otherwise all variations will be accepted
    #
    # Date: if date is not 0, assignments wich are earlier than this date will be returned
    #       otherwise returned assignments will be not filtred by date
    #
    # Paging: paging could be done with  @see take ans @see startWith
    #         take=0, startWith=0 means select all records;
    #
    #
    # @param [out] assingments
    # @param [in]  path
    # @param [in]  run
    # @param [in]  variation
    # @param [in]  date
    # @param [in]  take
    # @param [in]  startWith
    # @return
    #/
    #virtual vector<DAssignment *> GetAssignments(const string& path, const string& runName, const string& variation="", time_t date=0, int take=0, int startWith=0)=0;

    ##
    # @brief the function updates assignment comments
    # @param assignment
    # @return
    #/
    #------------------------------------------------
    #------------------------------------------------
    def update_assignment(self, assignment):
        self.session.commit()


    ##
    # @brief Deletes assignment
    # @param assignment object to delete. Must have valid ID
    # @return true if success
    #/
    def delete_assignment(self, assignment_obj):
        self.session.delete(assignment_obj)
        self.session.commit()


    ##
    # @brief Fill assignment with data if it has proper ID
    #
    # The function actually gets assignment by ID.
    #
    # A problem: is that for DB providers the id is assignment->GetId().
    #            For file provider the id is probably a type table full path
    # A solution:
    #    is to have this function that accepts DAssignment* assignment.
    #    DAssignment* assignment incapsulates the id (one way or another)
    #    And each provider could check if this DAssignment have valid Id,
    #    fill assignment with data and return true.
    #    Or just return "false" if something goes wrong;
    #
    # @param [in, out] assignment to fill
    # @return true if success and assignment was filled with data
    #/
    def fill_assignment(self, assignment):
        return self._provider.FillAssignment(assignment)

    def prepare_assignment_data(self):


#----------------------------------------------------------------------------------------
#	E R R O R   H A N D L I N G
#----------------------------------------------------------------------------------------


#----------------------------------------------------------------------------------------
#	O T H E R   F U N C T I O N S
#----------------------------------------------------------------------------------------

    ## @brief Validates name for constant type table or directory or column
    #
    # @param     string name
    # @return   bool
    #/
    def validate_name(self, name):
        return self._provider.ValidateName(name)

#----------------------------------------------------------------------------------------
#	L O G G I N G
#----------------------------------------------------------------------------------------
    @property
    def log_user_name(self):
        return self._provider.GetLogUserName()

    @log_user_name.setter
    def log_user_name(self, user_name):
        self._provider.SetLogUserName(user_name)
