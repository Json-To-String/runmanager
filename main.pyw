import os
import sys
import time
import random
import itertools
import logging, logging.handlers
import types
import subprocess
import threading
import urllib, urllib2, socket
if os.name == 'nt':
    import win32com.client

import gtk
import gobject
import pango

import h5py


import pylab
import excepthook
from fileops import FileOps

# This provides debug info without having to run from a terminal, and
# avoids a stupid crash on Windows when there is no command window:
#if not sys.stdout.isatty():
    #sys.stdout = sys.stderr = open('debug.log','w',1)
    
if os.name == 'nt':
    # Make it not look so terrible (if icons and themes are installed):
    gtk.settings_get_default().set_string_property('gtk-icon-theme-name','gnome-human','')
    gtk.settings_get_default().set_string_property('gtk-theme-name','Clearlooks','')
    gtk.settings_get_default().set_string_property('gtk-font-name','ubuntu 11','')
    gtk.settings_get_default().set_long_property('gtk-button-images',False,'')

    # Have Windows 7 consider this program to be a separate app, and not
    # group it with other Python programs in the taskbar:
    import ctypes
    myappid = 'monashbec.labscript.runmanager.2-0' # arbitrary string
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except:
        pass

def setup_logging():
    logger = logging.getLogger('RunManager')
    handler = logging.handlers.RotatingFileHandler(r'runmanager.log', maxBytes=1024*1024*50)
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s')
    handler.setFormatter(formatter)
    handler.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    if sys.stdout.isatty():
        terminalhandler = logging.StreamHandler(sys.stdout)
        terminalhandler.setFormatter(formatter)
        terminalhandler.setLevel(logging.INFO) # only display info or higher in the terminal
        logger.addHandler(terminalhandler)
    else:
        # Prevent bug on windows where writing to stdout without a command
        # window causes a crash:
        sys.stdout = sys.stderr = open(os.devnull,'w')
    logger.setLevel(logging.DEBUG)
    return logger

class CellRendererClickablePixbuf(gtk.CellRendererPixbuf):
    __gsignals__    = { 'clicked' :
                        (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (gobject.TYPE_STRING,)) , }
    def __init__(self):
        gtk.CellRendererPixbuf.__init__(self)
        self.set_property('mode', gtk.CELL_RENDERER_MODE_ACTIVATABLE)
    def do_activate(self, event, widget, path, background_area, cell_area, flags):
        self.emit('clicked', path)

class GroupTab(object):
    def __init__(self, runmanager, filepath, name):
        self.name = name
        self.filepath = filepath
        self.runmanager = runmanager
        self.notebook = self.runmanager.notebook
        self.vbox = runmanager.use_globals_vbox
        
        self.builder = gtk.Builder()
        self.builder.add_from_file('grouptab.glade')
        self.toplevel = self.builder.get_object('tab_toplevel')
        self.label_groupname = self.builder.get_object('label_groupname')
        self.label_h5_path = self.builder.get_object('label_h5_path')
        self.global_liststore = self.builder.get_object('global_liststore')
        self.global_treeview = self.builder.get_object('global_treeview')
        self.tab = gtk.HBox()
        
        self.delete_column = self.builder.get_object('delete_column')
        delete_cell_renderer = CellRendererClickablePixbuf()
        self.delete_column.pack_end(delete_cell_renderer)
        self.delete_column.add_attribute(delete_cell_renderer,"stock-id",3)
        delete_cell_renderer.connect("clicked",self.on_delete_global)
        
        #get a stock close button image
        close_image = gtk.image_new_from_stock(gtk.STOCK_CLOSE, gtk.ICON_SIZE_MENU)
        image_w, image_h = gtk.icon_size_lookup(gtk.ICON_SIZE_MENU)
        
        #make the close button
        btn = gtk.Button()
        btn.set_relief(gtk.RELIEF_NONE)
        btn.set_focus_on_click(False)
        btn.add(close_image)
        
        #this reduces the size of the button
        style = gtk.RcStyle()
        style.xthickness = 0
        style.ythickness = 0
        btn.modify_style(style)
        
        self.tablabel = gtk.Label(self.name)
        self.tablabel.set_ellipsize(pango.ELLIPSIZE_END)
        self.tablabel.set_tooltip_text(self.name)
        self.tab.pack_start(self.tablabel)
        self.tab.pack_start(btn, False, False)
        self.tab.show_all()
        self.notebook.append_page(self.toplevel, tab_label = self.tab)                     
        
        self.notebook.set_tab_reorderable(self.toplevel,True)
        
        self.label_groupname.set_text(self.name)
        self.label_h5_path.set_text(self.filepath)
        
        self.notebook.show()

        #connect the close button
        btn.connect('clicked', self.on_closetab_button_clicked)

        self.builder.connect_signals(self)
        
        self.globals = []
        
        global_vars, success = file_ops.get_globalslist(self.filepath,self.name)
        
        for global_var in global_vars:
            value,success = file_ops.get_value(self.filepath,self.name,global_var)
            units,success2 = file_ops.get_units(self.filepath,self.name,global_var)
            if success and success2:
                self.global_liststore.append((global_var,value,units,"gtk-delete",True,True))
            else:
                # TODO: Throw error
                pass
        
        # Add line to add a new global
        self.global_liststore.append(("<Click to add global>","","",None,False,False))
        
    def on_closetab_button_clicked(self,*args):
        # close tab
        self.close_tab()
        
        # change icon in group list view
        self.runmanager.close_tab(self.filepath,self.name)
        
    def update_name(self,new_name):
        self.name = new_name
        self.label_groupname.set_text(self.name)
        self.tablabel.set_text(self.name)
    
    def close_tab(self):
        # Get the page number of the tab we wanted to close
        pagenum = self.notebook.page_num(self.toplevel)
        # And close it
        self.notebook.remove_page(pagenum)
    
    def on_edit_name(self,cellrenderer,path,new_text):
        iter = self.global_liststore.get_iter(path)
        image = self.global_liststore.get(iter,3)[0]       
        # If the delete image is None, then add a new global!
        if not image:
            if new_text == "<Click to add global>":
                return
                
            success = file_ops.new_global(self.filepath,self.name,new_text)
            if success:
                add = self.global_liststore.insert_before(iter,(new_text,"","","gtk-delete",True,True))
                # TODO: Handle weird bug where hitting "tab" after typing the name causes the treeview rendering to break
                self.global_treeview.set_cursor(self.global_liststore.get_path(add),self.global_treeview.get_column(2),True)
                
        # We are editing an exiting global
        else:    
            name = self.global_liststore.get(iter,0)[0] 
            success = file_ops.rename_global(self.filepath, self.name, name, new_text)
            if success:
                self.global_liststore.set_value(iter,0,new_text)
        
    def on_edit_value(self,cellrenderer,path,new_text):
        iter = self.global_liststore.get_iter(path)
        name = self.global_liststore.get(iter,0)[0]  
        success = file_ops.set_value(self.filepath, self.name, name, new_text)
        if success:
            self.global_liststore.set_value(iter,1,new_text)
            # If the units box is empty, make it focussed and editable to encourage people to set units!
            units = self.global_liststore.get(iter,2)[0]  
            if not units:
                self.global_treeview.set_cursor(path,self.global_treeview.get_column(3),True)
    
    def on_edit_units(self,cellrenderer,path,new_text):
        iter = self.global_liststore.get_iter(path)
        name = self.global_liststore.get(iter,0)[0]  
        success = file_ops.set_units(self.filepath, self.name, name, new_text)
        if success:
            self.global_liststore.set_value(iter,2,new_text)
    
    def on_delete_global(self,cellrenderer,path):
        iter = self.global_liststore.get_iter(path)
        name = self.global_liststore.get(iter,0)[0] 
        image = self.global_liststore.get(iter,3)[0] 
        # If the image is None, we have the "<click here to add>" entry, ignore!
        if not image:
            return
        
        md = gtk.MessageDialog(self.runmanager.window, 
                                gtk.DIALOG_DESTROY_WITH_PARENT, gtk.MESSAGE_WARNING,gtk.BUTTONS_OK_CANCEL,
                                "Are you sure? \n\nThis will remove the global variable ("+name+") from the h5 file ("+self.filepath+") and cannot be undone.")
        md.set_default_response(gtk.RESPONSE_CANCEL)
        result = md.run()
        md.destroy()
        if result == gtk.RESPONSE_OK:
            success = file_ops.delete_global(self.filepath,self.name,name)
            if success:
                # Remove from the liststore
                self.global_liststore.remove(iter)
        
class RunManager(object):
    def __init__(self):
        self.builder = gtk.Builder()
        self.builder.add_from_file('interface2.glade')
        
        self.window = self.builder.get_object('window1')
        self.notebook = self.builder.get_object('notebook1')
        self.output_view = self.builder.get_object('textview1')
        self.output_adjustment = self.output_view.get_vadjustment()
        self.output_buffer = self.output_view.get_buffer()
        self.use_globals_vbox = self.builder.get_object('use_globals_vbox')
        self.grouplist_vbox = self.builder.get_object('grouplist_vbox')
        self.no_file_opened = self.builder.get_object('label_no_file_opened')
        #self.chooser_h5_file = self.builder.get_object('chooser_h5_file')
        self.chooser_labscript_file = self.builder.get_object('chooser_labscript_file')
        self.vbox_runcontrol = self.builder.get_object('vbox_runcontrol')
        self.scrolledwindow_output = self.builder.get_object('scrolledwindow_output')
        self.chooser_output_directory = self.builder.get_object('chooser_output_directory')
        self.checkbutton_parse = self.builder.get_object('checkbutton_parse')
        self.checkbutton_make = self.builder.get_object('checkbutton_make')
        self.checkbutton_compile = self.builder.get_object('checkbutton_compile')
        self.checkbutton_view = self.builder.get_object('checkbutton_view')
        self.checkbutton_run = self.builder.get_object('checkbutton_run')
        self.outputscrollbar = self.scrolledwindow_output.get_vadjustment()
        self.group_store = self.builder.get_object('group_store')
        self.group_treeview = self.builder.get_object('group_treeview')
        self.current_h5_store = self.builder.get_object('current_h5_store')
        self.current_h5_file = self.builder.get_object('current_h5_file')
        self.add_column = self.builder.get_object('add_column')
        add_cell_renderer = CellRendererClickablePixbuf()
        self.add_column.pack_end(add_cell_renderer)
        self.add_column.add_attribute(add_cell_renderer,"stock-id",2)
        add_cell_renderer.connect("clicked",self.on_toggle_group)
        
        self.delete_column = self.builder.get_object('delete_column')
        delete_cell_renderer = CellRendererClickablePixbuf()
        self.delete_column.pack_end(delete_cell_renderer)
        self.delete_column.add_attribute(delete_cell_renderer,"stock-id",3)
        delete_cell_renderer.connect("clicked",self.on_delete_group)
        
        #self.add_pixbuf.set_property('mode', gtk.CELL_RENDERER_MODE_ACTIVATABLE)
        #self.add_pixbuf.connect('activate',self.on_test)
        
        self.window.show()
        
        self.output_view.modify_font(pango.FontDescription("monospace 11"))
        self.output_view.modify_base(gtk.STATE_NORMAL, gtk.gdk.color_parse('black'))
        self.output_view.modify_text(gtk.STATE_NORMAL, gtk.gdk.color_parse('white'))
        
        self.window.set_icon_from_file(os.path.join('assets','icon.png'))
        self.builder.get_object('filefilter1').add_pattern('*.h5')
        self.builder.get_object('filefilter2').add_pattern('*.py')
        self.chooser_labscript_file.set_current_folder(r'C:\\user_scripts\\labscriptlib') # Will only happen if folder exists
        self.builder.connect_signals(self)
        #self.outputscrollbar.connect_after('value-changed', self.on_scroll)
        
        self.opentabs = []
        self.grouplist = []
        self.popped_out = False
        self.making_new_file = False
        self.parse = False
        self.make = False
        self.compile = False
        self.view = False
        self.run = False
        self.run_files = []
        self.aborted = False
        self.current_labscript_file = None
        self.text_mark = self.output_buffer.create_mark(None, self.output_buffer.get_end_iter())

        # Add timeout to watch for output folder changes when the day rolls over
        #gobject.timeout_add(1000, self.update_output_dir)
        self.current_day = time.strftime('\\%Y-%b\\%d')
        
        self.output('Ready\n')
    
    def on_window_destroy(self,widget):
        gtk.main_quit()
    
    def output(self,text,red=False):
        """Prints text to the output textbox and to stdout"""
        print text, 
        # Check if the scrollbar is at the bottom of the textview:
        scrolling = self.output_adjustment.value == self.output_adjustment.upper - self.output_adjustment.page_size
        # We need the initial cursor position so we know what range to make red:
        offset = self.output_buffer.get_end_iter().get_offset()
        # Insert the text at the end:
        self.output_buffer.insert(self.output_buffer.get_end_iter(), text)
        if red:
            start = self.output_buffer.get_iter_at_offset(offset)
            end = self.output_buffer.get_end_iter()
            # Make the text red:
            self.output_buffer.apply_tag(self.output_buffer.create_tag(foreground='red'),start,end)
            self.output_buffer.apply_tag(self.output_buffer.create_tag(weight=pango.WEIGHT_BOLD),start,end)

        # Automatically keep the textbox scrolled to the bottom, but
        # only if it was at the bottom to begin with. If the user has
        # scrolled up we won't jump them back to the bottom:
        if scrolling:
            self.output_view.scroll_to_mark(self.text_mark,0)
    
    def pop_out_in(self,widget):
        if not self.popped_out and not isinstance(widget,gtk.Window):
            self.popped_out = not self.popped_out
            self.vbox_runcontrol.remove(self.scrolledwindow_output)
            screen = gtk.gdk.Screen()
            window = gtk.Window()
            window.add(self.scrolledwindow_output)
            window.connect('destroy',self.pop_out_in)
            window.resize(800,800)#self.window.get_size()[1])
            window.set_title('labscript run manager output')
            icon_theme = gtk.icon_theme_get_default()
            pb = icon_theme.load_icon('utilities-terminal', gtk.ICON_SIZE_MENU,0)
            window.set_icon(pb)
            window.show()
            self.builder.get_object('button_popout').hide()
            self.builder.get_object('button_popin').show()
        elif self.popped_out:
            self.popped_out = not self.popped_out
            window = self.scrolledwindow_output.get_parent()
            window.remove(self.scrolledwindow_output)
            self.vbox_runcontrol.pack_start(self.scrolledwindow_output)
            self.vbox_runcontrol.show()
            if not isinstance(widget,gtk.Window):
                window.destroy()
            self.builder.get_object('button_popout').show()
            self.builder.get_object('button_popin').hide()
        while gtk.events_pending():
            gtk.main_iteration()
        self.output_view.scroll_to_mark(self.text_mark,0)
    
    def toggle_parse(self,widget):
        self.parse = widget.get_active()
        if not self.parse:
            self.checkbutton_make.set_active(False)
            self.checkbutton_compile.set_active(False)
            self.checkbutton_view.set_active(False)
            self.checkbutton_run.set_active(False)
           
    def toggle_make(self,widget):
        self.make = widget.get_active()
        if self.make:
            self.checkbutton_parse.set_active(True)
        else:
            self.checkbutton_compile.set_active(False)
            self.checkbutton_view.set_active(False)
            self.checkbutton_run.set_active(False)        
    
    def toggle_compile(self,widget):
        self.compile = widget.get_active()
        if self.compile:
            self.checkbutton_parse.set_active(True)
            self.checkbutton_make.set_active(True)
        else:
            self.checkbutton_view.set_active(False)
            self.checkbutton_run.set_active(False) 
    
    def toggle_view(self,widget):
        self.view = widget.get_active()
        if self.view:
            self.checkbutton_parse.set_active(True)
            self.checkbutton_make.set_active(True)
            self.checkbutton_compile.set_active(True) 
            
    def toggle_run(self,widget):
        self.run = widget.get_active()
        if self.run:
            self.checkbutton_parse.set_active(True)
            self.checkbutton_make.set_active(True)
            self.checkbutton_compile.set_active(True) 
    
    def on_new_file_clicked(self,*args):
        chooser = gtk.FileChooserDialog(title='Save new HDF5 file',action=gtk.FILE_CHOOSER_ACTION_SAVE,
                                    buttons=(gtk.STOCK_CANCEL,gtk.RESPONSE_CANCEL,
                                               gtk.STOCK_SAVE,gtk.RESPONSE_OK))
        chooser.add_filter(self.builder.get_object('filefilter1'))
        chooser.set_default_response(gtk.RESPONSE_OK)
        chooser.set_do_overwrite_confirmation(True)
        # set this to the current location of the h5_chooser
        #if self.chooser_h5_file.get_current_folder():            
        #    chooser.set_current_folder(self.chooser_h5_file.get_current_folder())
            
        chooser.set_current_name('.h5')
        response = chooser.run()
        f = chooser.get_filename()
        d = chooser.get_current_folder()
        chooser.destroy()
        if response == gtk.RESPONSE_OK:
            success = file_ops.new_file(f)
            if not success:
                # Throw error
                pass
            
            # Append to Tree View
            parent = self.group_store.prepend(None,(f,False,"gtk-add","gtk-delete",0,0,1))
            # Add editable option for adding!
            self.group_store.append(parent,("<Click to add group>",False,None,None,0,1,0))  
            
    def on_global_toggle(self, cellrenderer_toggle, path):
        new_state = not cellrenderer_toggle.get_active()
        # Update the toggle button
        iter = self.group_store.get_iter(path)
        self.group_store.set_value(iter,1,new_state)
        
        # Toggle buttons that have been clicked are never in an inconsitent state
        self.group_store.set_value(iter,4,False)      
        
        
        # Does it have children? (aka a top level in the tree)
        if self.group_store.iter_has_child(iter):
            child_iter = self.group_store.iter_children(iter)
            while child_iter:
                self.group_store.set_value(child_iter,1,new_state)
                child_iter = self.group_store.iter_next(child_iter)
        # Is it a child?
        elif self.group_store.iter_depth(iter) > 0:
            # check to see if we should set the parent (top level) checkbox to an inconsistent state!
            self.update_parent_checkbox(iter,new_state)
            
    def update_parent_checkbox(self,iter,child_state):
        # Get iter for top level
        parent_iter = self.group_store.iter_parent(iter)
        
        # Are the children in an inconsitent state?
        child_iter = self.group_store.iter_children(parent_iter)
        if child_iter:
            inconsistent = False
            first_state = self.group_store.get(child_iter,1)[0]
            while child_iter:
                # If state doesn't mathc the first one and the options are visible (not the child used to add a new group)
                # Then break out and set the state to inconsistent
                if self.group_store.get(child_iter,1)[0] != first_state and self.group_store.get(child_iter,6)[0]:
                    inconsistent = True             
                    break
                child_iter = self.group_store.iter_next(child_iter)
        # All the children have been deleted!
        else:
            inconsistent = False
            first_state = False
        
        self.group_store.set_value(parent_iter,4,inconsistent)
        
        # If we are not in an inconsistent state, make sure the parent checkbox matches the children
        if not inconsistent:
            if child_state == None:
                # Use the first_state!
                child_state = first_state
            self.group_store.set_value(parent_iter,1,child_state)
    
    def on_open_h5_file(self, *args):      
        chooser = gtk.FileChooserDialog(title='OpenHDF5 file',action=gtk.FILE_CHOOSER_ACTION_OPEN,
                                    buttons=(gtk.STOCK_CANCEL,gtk.RESPONSE_CANCEL,
                                               gtk.STOCK_SAVE,gtk.RESPONSE_OK))
        chooser.add_filter(self.builder.get_object('filefilter1'))
        chooser.set_default_response(gtk.RESPONSE_OK)
        # set this to the current location of the h5_chooser
        #if self.chooser_h5_file.get_current_folder():            
            #chooser.set_current_folder(self.chooser_h5_file.get_current_folder())
            
        chooser.set_current_name('.h5')
        response = chooser.run()
        f = chooser.get_filename()
        d = chooser.get_current_folder()
        chooser.destroy()
        if response == gtk.RESPONSE_OK:
            # Check that the file isn't already in the list!
            iter = self.group_store.get_iter_root()
            while iter:
                fp = self.group_store.get(iter,0)[0]
                if fp == f:
                    return
                iter = self.group_store.iter_next(iter)
            
            # open the file!            
            grouplist, success = file_ops.get_grouplist(f) 
            if success:
                # Append to Tree View
                parent = self.group_store.prepend(None,(f,False,"gtk-add","gtk-delete",0,0,1))            
                for name in grouplist:
                    self.group_store.append(parent,(name,False,"gtk-add","gtk-delete",0,1,1))  
                                
                self.group_treeview.expand_row(self.group_store.get_path(parent),True) 
                # Add editable option for adding!
                add = self.group_store.append(parent,("<Click to add group>",False,None,None,0,1,0)) 
                self.group_treeview.set_cursor(self.group_store.get_path(add),self.group_treeview.get_column(3),True)

    def on_add_group(self,cellrenderer,path,new_text):
        # Find the filepath      
        iter = self.group_store.get_iter(path)
        parent = self.group_store.iter_parent(iter)
        filepath = self.group_store.get(parent,0)[0]
        image = self.group_store.get(iter,2)[0]
        
        # If the image is none, then this is an entry for adding global groups
        if not image:        
            # Ignore if theyhave clicked in the box, and then out!
            if new_text == "<Click to add group>":
                return
        
                  
            success = file_ops.new_group(filepath, new_text)
            if success:
                self.group_store.insert_before(parent,iter,(new_text,True,"gtk-close","gtk-delete",0,1,1))
                # Update parent checkbox state
                self.update_parent_checkbox(iter,True)
                
                # Automatically open this new group!
                self.opentabs.append(GroupTab(self,filepath,new_text))
        
        else:
            # We want to rename an existing group!
            old_name = self.group_store.get(iter,0)[0]
            success = file_ops.rename_group(filepath,old_name,new_text)
            if success:
                self.group_store.set_value(iter,0,new_text)
                
                # TODO: Update the names in the open groups!
                for group in self.opentabs:
                    if group.filepath == filepath and group.name == old_name:
                        group.update_name(new_text)
                        break
        
    def on_delete_group(self,cellrenderer,path):
        iter = self.group_store.get_iter(path)
        
        image = self.group_store.get(iter,3)[0]
        # If the image is None, we have the <"click here to add>" entry, so ignore!
        if not image:
            return
        
        # If we have a top level row (a h5 file), then ask if the file should be deleted!
        if self.group_store.iter_depth(iter) == 0:
            pass
        
        # Else we want to delete a group!
        else:
            # Find the parent filename
            parent = self.group_store.iter_parent(iter)
            filepath = self.group_store.get(parent,0)[0]

            # get the group name
            group_name = self.group_store.get(iter,0)[0]
            
            md = gtk.MessageDialog(self.window, 
                                    gtk.DIALOG_DESTROY_WITH_PARENT, gtk.MESSAGE_WARNING, 
                                    buttons =(gtk.BUTTONS_OK_CANCEL),
                                    message_format = "Are you sure? This will remove the group ("+group_name+") from the h5 file ("+filepath+") and cannot be undone.")
            md.set_default_response(gtk.RESPONSE_CANCEL)
            result = md.run()
            md.destroy()
            if result == gtk.RESPONSE_OK:
                success = file_ops.delete_group(filepath,group_name)
                
                if success:
                    # Remove the row from the treeview
                    self.group_store.remove(iter)
                    
                    # Update state of parent checkbox
                    self.update_parent_checkbox(iter,None)
                    
                    # TODO: Close the open group tab!
                else:
                    # TODO: Throw error message
                    pass
                
    
    def on_toggle_group(self,cellrenderer,path):
        iter = self.group_store.get_iter(path)  

        # TODO: Handle clicking the +/x button on a toplevel entry (a h5 file)
        #       This should open all groups if not all are open, or close all groups if all are open
        
        image = self.group_store.get(iter,2)[0]
        name = self.group_store.get(iter,0)[0]
        filepath = self.group_store.get(self.group_store.iter_parent(iter),0)[0]
        
        # TODO: Ignore "add entry" where there is no image
        # TODO: open/close all groups if +/x is clicked next to h5 file name
        # TODO: Implement closing of groups
        
        if image == "gtk-add":
            self.group_store.set_value(iter,2,"gtk-close")
            self.opentabs.append(GroupTab(self,filepath,name))
        elif image == "gtk-close":
            # update the icon in the group list
            self.group_store.set_value(iter,2,"gtk-add")
            # close the tab!
            # Note we don't use the close tab functionality as we already have the iterator.
            # Instead we just find the GroupTab, remove it from the list, and ask it to delete itself
            # (calling gt.close_tab does not invoke the close_tab function in the RunManager class 
            for gt in self.opentabs:
                if gt.filepath == filepath and gt.name == name:
                    gt.close_tab()
                    self.opentabs.remove(gt)
                    break
        else:
            # no image, which means the "<click here to add"> line, so return!
            return
    
    # This function is poorly named. It actually only updates the +/x icon in the group list!   
    # This function is called by the GroupTab class to clean up the state of the group treeview
    def close_tab(self,filepath,group_name):
        # find entry in treemodel
        iter = self.group_store.get_iter_root()
        
        while iter:
            fp = self.group_store.get(iter,0)[0]
            if fp == filepath:
                # find group entry
                iter2 = self.group_store.iter_children(iter)
                while iter2:
                    gn = self.group_store.get(iter2,0)[0]
                    if gn == group_name:
                        # Change icon
                        self.group_store.set_value(iter2,2,"gtk-add")
                        # remove the tab from the list!
                        for gt in self.opentabs:
                            if gt.filepath == filepath and gt.name == group_name:
                                self.opentabs.remove(gt)
                                break
                        break
                    iter2 = self.group_store.iter_next(iter2)
                break
            iter = self.group_store.iter_next(iter)
    
logger = setup_logging()
excepthook.set_logger(logger)
if __name__ == "__main__":
    logger.info('\n\n===============starting===============\n')
    gtk.gdk.threads_init()
    
    run_manager = RunManager()
    file_ops = FileOps(run_manager)
    
    with gtk.gdk.lock:
        gtk.main()