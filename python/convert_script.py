from xml.dom.minidom import parse, parseString
from os import environ, path
from xml.dom import minidom
import xml.dom.minidom
import os
import os.path
import sys
import ccdb

dom = xml.dom.minidom.getDOMImplementation();
#dom = xml.dom.dom()
print """
============================
SVN CALIB to CCDB convertion
============================

This script aims to convers SVN file based GluEx calibration constats set to CCDB database

Three environment variables must be set:
CCDB_HOME - ccdb package home dir
JANA_CALIB_URL - Jana callib url in form of file://path/to/data
JANA_CALIB_RULES - path to xml files with conversion rules 

run this script with '--rehearsal' flag to see what will be done. 
run this script with '--execute' flag will execute ccdb commands
"""


#--------------------------
#  CONFIGURE  CCDB  PACKAGE 
#-------------------------- 

#ccdb pakage path
if not "CCDB_HOME" in os.environ:
    print "CCDB_HOME must be set"
    exit(1)

ccdb_dir = os.environ['CCDB_HOME']

# configure ccdb package to use
try:
    import ccdb.ccdb_pyllapi
except:
    ccdb_python_dir = os.path.join(ccdb_dir, 'python')
    sys.path.append(ccdb_python_dir)
    try:
        import ccdb.ccdb_pyllapi
    except:
        print "Cannot load ccdb_pyllapi. Check it is in path"
        exit(1)

#configure ccdbcmd
ccdbcmd_opts = ""


#--------------------------------------------
# *** CONFIGURE  SVN CALIBRATION  PACKAGE ***
#--------------------------------------------

if not "JANA_CALIB_URL" in  os.environ:
    print "JANA_CALIB_URL must be set"
    exit(1)

#this is directory with calib data
calib_dir = os.environ['JANA_CALIB_URL']
calib_dir = calib_dir[7:] #skip 'file://' part

#-------------------------------------
# *** CONFIGURE  CONVERSION RULES  ***
#-------------------------------------

if not "JANA_CALIB_RULES" in  os.environ:
    print "JANA_CALIB_RULES must be set"
    exit(1)

#this is 'rules dir' the directory where xml files with data table definition are located
rules_dir = os.environ['JANA_CALIB_RULES']
rules_xml_dir = os.path.join(rules_dir, 'xml')


#-----------------------------
# *** PRINT CONFIGURATION  ***
#-----------------------------
print "CCDB path: "
print "   " + ccdb_dir
print "CCDB options: "
print "    '" + ccdbcmd_opts + "'"
print "JANA svn calibrations path:"
print "   " + calib_dir
print "conversion rules base dir: "
print "   " + rules_dir
print "converion rules xml dir: " 
print "    " + rules_xml_dir

#-----------------------------
# ***    PARSE XML DIRS    ***
#-----------------------------
dirs_xmldoc = minidom.parse(os.path.join(rules_xml_dir, 'directory.xml')) 
xml_dirs_names = [f.attributes["name"].value for f in dirs_xmldoc.getElementsByTagName('directory')]

#-----------------------------
# ***    PARSE ARGS        ***
#-----------------------------
import argparse
 
parser = argparse.ArgumentParser(description='Converts existing svn HallD collibrations to CCDB callibrations.')
parser.add_argument('-r','--rehearsal', action="store_true", default=False, help='Run script to view what will be done. Script will run everything, but instead of invoking ccdbcmd commands, they will be printed on screen') 
parser.add_argument('-e','--execute', action="store_true", default=False, help='Run script and execute ccdbcmd commands')
parser.add_argument('-v','--verbose', action="store_true", default=False, help='Print additional info')
result = parser.parse_args()
#(execute_commands, is_reharsal) = result

execute_ccdb_commands = result.execute
is_reharsal = result.rehearsal
is_verbose = result.verbose

print " execute_commands " + repr(execute_ccdb_commands)
print " is_reharsal " + repr(is_reharsal)
print " is verbose " + repr(is_verbose)


#-----------------------------------------------------"
# process_file
#-----------------------------------------------------"
def process_file(home_dir, rule_file_name, ccdb_parent_path):
    
    #parse xml file
    rule_file_path = os.path.join(home_dir, rule_file_name);
    xmldoc = minidom.parse(rule_file_path) 
    print "  Processing file " + rule_file_path
    print "  ***********************************************"
    
    #iterate type tables
    xml_tables = xmldoc.getElementsByTagName('type')
    for xml_table in xml_tables:
        table_name = xml_table.attributes['name'].value
        nrows = int(xml_table.attributes['nrow'].value)
        is_name_value_format = bool(int(xml_table.attributes['namevalue'].value))
        comments = ''
        xml_comments = xml_table.getElementsByTagName('comment')
        if len(xml_comments):
            comments = " ".join(t.nodeValue for t in xml_comments[0].childNodes if t.nodeType == t.TEXT_NODE)
        comments.replace("\r\n", "\\n")
        comments.replace("\n","\\n")
        comments.replace('"',"'")

        

            #comments = comments.replace("\\n",os.linesep)
        

        print "    Found table: " + table_name
        print "    Comments: " 
        print "    " + comments[0:50]
        print "    Rows Number: " + str(nrows)
        print "    Is namevalue: " + repr(is_name_value_format);
       
        
        #iterate columns
        columns_create_command = ''
        xml_columns = xml_table.getElementsByTagName('column')
        if not is_verbose: print "    Columns : " + repr(len(xml_columns))
        else: print "    Columns: "
        for xml_column in xml_columns:
            column_name = xml_column.attributes['name'].value
            column_type = xml_column.attributes['type'].value
            if(is_verbose): print "      {:<35} ({})".format(column_name, column_type)
            columns_create_command+=' "{}({})"'.format(column_name, column_type)
        table_path = (ccdb_parent_path + "/" + table_name).replace("//","/")
        create_table_command = 'ccdbcmd ' + ccdbcmd_opts +' mktbl {0} -r {1} {2} "#{3}"'
        create_table_command = create_table_command.format(table_path, nrows, columns_create_command, comments)

        print "    Create command"
        print "    " + create_table_command
#        print "    " + create_table_command[0:50]+" ... "
        if(execute_ccdb_commands): os.system(create_table_command)
        
        print
        print "  Filling data "
        print "  ============================================="
        

        #now fill it with data

        data_file_path = os.path.join(ccdb_parent_path, table_name)
        data_file_path = (calib_dir + "/" + data_file_path).replace("//","/")
        print "    Data file is: " + data_file_path

        dom = ccdb.TextFileDOM()
        dom = ccdb.read_namevalue_text_file(data_file_path)
        
        if is_verbose:
            print dom.column_names
            print dom.rows
            for i in range(min(len(dom.column_names),50)):
                print "{:>35}     {}".format(dom.column_names[i], dom.rows[0][i])

        add_command = "ccdbcmd " + ccdbcmd_opts + " add "
        if(is_name_value_format) : add_command += "--name-value "
        add_command += table_path +" -v default -r 0- " + data_file_path
        print add_command
        
        if(execute_ccdb_commands): os.system(add_command)
        print "  ============================================="
        print "  Finished with file "
        


#-----------------------------------------------------"
# process_directories
#-----------------------------------------------------"
def process_directories(home_dir):
    """ Create all directories according to rules_xml_dir"""
    
    print
    print "-----------------------------------------------------"
    print "Entered directory  " + home_dir
    print "-----------------------------------------------------"
    sub_dirs = [f for f in os.listdir(home_dir) if os.path.isdir(os.path.join(home_dir, f))]    
    if not len(sub_dirs): return

    ccdb_parent_path = home_dir[len(rules_xml_dir):].replace("\\","/")
    print "CCDB parent path that corresponds to this directory: "
    print ccdb_parent_path
    print

    #get files
    sub_files = [f for f in os.listdir(home_dir) if os.path.isfile(os.path.join(home_dir, f))]
    
    #iterate through files and process xml files
    for filename in sub_files:
        if not filename.endswith(".xml"): continue
        process_file(home_dir, filename, ccdb_parent_path)

    
    print "Scanning for subdirectories"
    for directory in sub_dirs:
        if directory == '.svn': continue
        print "found subdirectory " + directory
        create_directory(directory, ccdb_parent_path)
        process_directories(os.path.join(home_dir, directory))


    #print "Xml dir names"
    #for xml_name in xml_dirs_names:
    #    print xml_name
    #create_directory(dir, '/')

    pass

#----------------------------------
def create_directory(dir_name, parent_path):
    path = (parent_path + "/" + dir_name).replace("//","/")
    print "creating ccdb directory: " + path
    command = "ccdbcmd " + ccdbcmd_opts + " mkdir " + path
    print command
    if(execute_ccdb_commands): os.system(command)


if execute_ccdb_commands or is_reharsal:
    process_directories(rules_xml_dir);

    