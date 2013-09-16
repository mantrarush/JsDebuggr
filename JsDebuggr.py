# JsDebuggr 0.5.8

import sublime
import sublime_plugin
import uuid
import re

#settings, duh
settings = sublime.load_settings("JsDebuggr.sublime-settings")

#colors for the breakpoint gutter markers
BREAK_SCOPE = settings.get("breakpoint_color")
BREAK_DISABLED_SCOPE = settings.get("disabled_breakpoint_color")
CONDITIONAL_SCOPE = settings.get("conditional_breakpoint_color")

#file extensions to track breakpoints in. default is js, html, and htm
#TODO - isntead, use sublime's scopes to determine if this is a javascript context
FILE_TYPE_LIST = settings.get("file_type_list")

#if set to true, and existing JsDbg debugger; statements will be
#converted to breakpoints automatically. if false, they will be left
#in tact
AUTOSCAN_ON_LOAD = settings.get("autoscan_on_load")

#used with printl() function which is just a proxy for print() except
#it checks if VERBOSE is true. turn this off to turn off console debugging
VERBOSE = settings.get("verbose")

#the debugger; statement to be inserted at each breakpoint. the 
#/*JsDbg*/ thing is to give JsDebuggr a unique string to search
#for when adding and removing breakpoints
DEBUG_STATEMENT = "/*JsDbg*/debugger;"
#beginning and end marker for the conditional part of a conditional
#breakpoint. this is kinda obtuse and hacky...
CONDITIONAL_BEGIN_MARKER = "/*JsDbg-Begin*/"
CONDITIONAL_END_MARKER = "/*JsDbg-End*/"

#coffeescript style comments
COFFEE_FILE_TYPE_LIST = settings.get("coffeescript_filetypes")

#dict which stores a bool indicating if a view should
#be tracked by JsDebuggr. the view id is the dict key
#this dict is populated by should_track_view()
#TODO - can probably use is_enabled() to replace this
track_view = {}


#determines if a view should track breakpoints and stuff.
#TODO - is it ok to leave this guy global like this? seems bad...
#TODO - can probably use is_enabled() instead of this (or at least
#   trim it down a bit)
def should_track_view(view, force=False):
    viewId = str(view.id())
    #determine if this viewId should be tracked by plugin
    #if this determination hasn't been made before, figure it out
    if not viewId in track_view or force:
        #TODO - use settings instead of hardcoded constants
        #settings = sublime.load_settings("JsDebuggr.sublime-settings")

        file_type_list = FILE_TYPE_LIST
        file_name = view.file_name()
        if not file_name:
            #if this is an unnamed document, don't track
            file_name = ""
        extension = file_name.split(".")[-1]
        if not extension in file_type_list:
            printl("JsDebuggr: Not tracking document because it is not of the correct type.")
            track_view[viewId] = False
            #TODO - remove event listeners?
            #TODO - disable context menu?
        else:
            track_view[viewId] = True

    #printl("JsDebuggr: should_track_view() returning %s" % track_view[viewId])
    return track_view[viewId]


#easy way to turn console logging on and off
def printl(str):
    if VERBOSE:
        print(str)


#TODO - feels like global like this is bad design
#big ol global list of all the breakpointLists, indexed by view.id()
breakpointLists = {}


#either returns an existing breakpoint list for the current view
#or creates a new one
def get_breakpointList(view):
    viewId = str(view.id())
    if not viewId in breakpointLists:
        printl("JsDebuggr: creating new BreakpointList")

        #determine if this is a coffeescript file. if so, specify
        #that in BreakpointList. fix for https://github.com/rDr4g0n/JsDebuggr/issues/20
        coffee = False
        extension = view.file_name().split(".")[-1]
        if extension in COFFEE_FILE_TYPE_LIST:
            printl("JsDebuggr: this is a coffeescript file")
            coffee = True

        breakpointLists[viewId] = BreakpointList(view, coffee)

    return breakpointLists[viewId]


#gets the line numbers that current cursors are on. right now
#i am just interested in the first one, but in the future i might
#use the others to do multiple selections
def get_line_nums(view):
    lineNums = []
    for s in view.sel():
        lineNums.append(view.rowcol(s.a)[0] + 1)
    return lineNums


#collection containing a list of breakpoints and a number
#of functions for retrieving, removing, sorting, and also
#handles drawing the breakpoint circle in the gutter
class BreakpointList():
    def __init__(self, view, coffee=False):
        self.breakpoints = {}
        self.numLines = 0
        self.view = view
        self.coffee = coffee

    def get(self, lineNum):
        lineNumStr = str(lineNum)
        if lineNumStr in self.breakpoints:
            return self.breakpoints[lineNumStr]
        else:
            return None

    #returns True if a new break is created. returns
    #false if the break existed but is now removed
    def toggle(self, lineNum):
        if lineNum is None:
            return

        lineNumStr = str(lineNum)

        #check if breakpoint is already stored
        if lineNumStr in self.breakpoints:
            self.remove(lineNum)
            return False
        #create a new Breakpoint
        else:
            self.add(lineNum)
            return True

    def add(self, lineNum, condition=None):
        lineNumStr = str(lineNum)

        #if there is already a breakpoint for this line, remove it
        if lineNumStr in self.breakpoints:
            self.remove(lineNum)

        printl("JsDebuggr: creating new breakpoint for line %i" % lineNum)
        breakpoint = Breakpoint(**{
            "lineNum": lineNum,
            "condition": condition,
            "coffee": self.coffee
        })
        #register breakpoint
        self.breakpoints[lineNumStr] = breakpoint
        #draw the icon
        self.draw_gutter_icon(breakpoint)

        return breakpoint

    def remove(self, lineNum):
        lineNumStr = str(lineNum)
        printl("JsDebuggr: removing breakpoint for line %s" % lineNumStr)
        #clear the icon
        self.clear_gutter_icon(self.breakpoints[lineNumStr].id)
        #remove from breakpoints registry
        del self.breakpoints[lineNumStr]

    def remove_all(self):
        #TODO - creating lineNumList can be done in a more pythonic way
        #   im just not sure what it is. once I figure that out i can
        #   make this just one loop instead of 2
        lineNumList = []
        for id in self.breakpoints:
            lineNumList.append(id)
        for lineNum in lineNumList:
            self.remove(lineNum)

    def enable(self, lineNum):
        lineNumStr = str(lineNum)
        breakpoint = self.breakpoints[lineNumStr]
        breakpoint.enabled = True
        if breakpoint.condition:
            breakpoint.scope = CONDITIONAL_SCOPE
        else:
            breakpoint.scope = BREAK_SCOPE
        self.draw_gutter_icon(breakpoint)

    def disable(self, lineNum):
        lineNumStr = str(lineNum)
        breakpoint = self.breakpoints[lineNumStr]
        breakpoint.enabled = False
        breakpoint.scope = BREAK_DISABLED_SCOPE
        self.draw_gutter_icon(breakpoint)

    def disable_all(self):
        for lineNum in self.breakpoints:
            self.disable(int(lineNum))

    def enable_all(self):
        for lineNum in self.breakpoints:
            self.enable(int(lineNum))

    #looks up breakpoints by id and updates their lineNum in
    #the breakpoint list.
    def shift(self):
        newBreakpoints = {}

        for lineNum in self.breakpoints:
            breakpoint = self.breakpoints[lineNum]

            #get the region that the marker is on
            region = self.view.get_regions(breakpoint.id)
            if region:
                #get the line number of that region
                regionLineNum = self.view.rowcol(region[0].a)[0] + 1
                regionLineNumStr = str(regionLineNum)

                if regionLineNumStr in newBreakpoints:
                    #more than one breakpoint was shifted to this line
                    #so clear the previous one before merging. fixes for bug
                    #https://github.com/rDr4g0n/JsDebuggr/issues/13
                    printl("JsDebuggr: multiple breakpoints merged")
                    self.clear_gutter_icon(newBreakpoints[regionLineNumStr].id)

                printl("JsDebuggr: shifting %s to %i" % (lineNum, regionLineNum))
                #switch this breakpoint to that line number
                breakpoint.lineNum = regionLineNum
                newBreakpoints[regionLineNumStr] = breakpoint
            else:
                printl("JsDebuggr: removing %s" % lineNum)

        #update the global breakpoint list with the new one
        self.breakpoints = newBreakpoints

    def draw_gutter_icon(self, breakpoint):
        line = self.view.line(self.view.text_point(breakpoint.lineNum - 1, 0))
        self.view.add_regions(breakpoint.id, [line], breakpoint.scope, "circle", sublime.HIDDEN | sublime.PERSISTENT)

    def clear_gutter_icon(self, id):
        self.view.erase_regions(id)


#model containing information about each breakpoint
class Breakpoint():
    def __init__(self, lineNum=0, enabled=True, scope=BREAK_SCOPE, debugger=DEBUG_STATEMENT, condition=False, coffee=False):
        #unique id used in drawing and clearing gutter icons
        self.id = str(uuid.uuid4())
        #the line number that this breakpoint is associated with
        self.lineNum = lineNum
        #if enabled is false, no debugger; statement will be generated
        #for this breakpoint at save time
        self.enabled = True
        #sets the color of the gutter icon
        self.scope = scope
        #the debugger statement to insert. if this is a conditional      
        if coffee:
            self.debugger = "`%s`" % debugger
        else:
            self.debugger = debugger
        #if this is a conditional breakpoint, the user supplied
        #condition is saved here
        self.condition = condition
        #if this is coffeescript, make note so that proper debugger statements
        #can be used
        self.coffee = coffee

        if self.condition:
            self.set_condition(condition)

    #sets up the breakpoint as conditional and constructs the debugger
    #statement that includes the condition
    def set_condition(self, condition):
        self.condition = condition

        if self.coffee:
            #TODO - should the conditional be pure js or coffeescript?
            self.debugger = "`if(%s%s%s){%s}`" % (CONDITIONAL_BEGIN_MARKER, self.condition, CONDITIONAL_END_MARKER, DEBUG_STATEMENT)
        else:
            self.debugger = "if(%s%s%s){%s}" % (CONDITIONAL_BEGIN_MARKER, self.condition, CONDITIONAL_END_MARKER, DEBUG_STATEMENT)

        #HACK - setting CONDITIONAL_SCOPE here is all hacksy
        self.scope = CONDITIONAL_SCOPE
        printl("JsDebuggr: conditional break: %s" % self.debugger)


# handle text commands from user
#TODO - break these out into separate commands so that
#   i can use is_visible() to turn them on and off
class JsDebuggr(sublime_plugin.TextCommand):

    def is_visible(self):
        return True

    def run(self, edit, **options):
        if not should_track_view(self.view):
            printl("JsDebuggr: ignoring request as this view isn't being tracked")
            return

        breakpointList = get_breakpointList(self.view)

        if(options and "removeAll" in options):
            breakpointList.remove_all()
        elif(options and "toggleEnable" in options):
            self.toggle_enable_break()
        elif(options and "enableAll" in options):
            breakpointList.enable_all()
        elif(options and "disableAll" in options):
            breakpointList.disable_all()
        elif(options and "conditional" in options):
            self.add_conditional_input()
        elif(options and "editConditional" in options):
            self.edit_conditional_input()
        else:
            self.toggle_break() 

    #determines which line is currently selected and checks if
    #a breakpoint is on that line. then decides to remove it, or
    #create a new breakpoint.
    def toggle_break(self):
        breakpointList = get_breakpointList(self.view)

        #TODO - deal with multiple selection
        lineNum = get_line_nums(self.view)[0]

        breakpoint = breakpointList.get(lineNum)

        if breakpoint:
            #breakpoint exists, so turn it off.
            breakpointList.remove(lineNum)
        else:
            #else, create a new one
            breakpoint = breakpointList.add(lineNum)

    #determines which line is currently selected and checks if
    #a breakpoint is on that line. then decides to enable or
    #disable it.
    def toggle_enable_break(self):
        breakpointList = get_breakpointList(self.view)
        lineNum = get_line_nums(self.view)[0]
        breakpoint = breakpointList.get(lineNum)

        if breakpoint.enabled:
            #breakpoint is enabled, so disable it
            printl("JsDebuggr: disabling breakpoint")
            breakpointList.disable(lineNum)
        else:
            #breakpoint is disabled, so enabled it
            printl("JsDebuggr: enabling breakpoint")
            breakpointList.enable(lineNum)

    #brings up input panel to enter the conditional statement
    #to be used with a conditional breakpoint
    def add_conditional_input(self):
        self.view.window().show_input_panel("Enter Condition:", "", self.add_conditional, None, None)

    #creates a new breakpoint, setting the conditional property
    #from the user supplied text.
    def add_conditional(self, text):
        breakpointList = get_breakpointList(self.view)
        lineNum = get_line_nums(self.view)[0]
        breakpointList.add(lineNum, text)

    #looks up the existing breakpoints conditional property
    #and brings up an input panel prepopulated with the current
    #condition for editing.
    def edit_conditional_input(self):
        breakpointList = get_breakpointList(self.view)
        lineNum = get_line_nums(self.view)[0]
        breakpoint = breakpointList.get(lineNum)
        if breakpoint.condition:
            self.view.window().show_input_panel("Enter Condition:", breakpoint.condition, self.edit_conditional, None, None)

    #updates the existing conditional breakpoint with new condition
    def edit_conditional(self, text):
        printl(text)
        breakpointList = get_breakpointList(self.view)
        lineNum = get_line_nums(self.view)[0]
        breakpoint = breakpointList.get(lineNum)
        breakpoint.set_condition(text)
        #TODO - set_status probably doesn't belong here
        self.view.set_status(breakpoint.id, "JsDebuggr Condition: `%s`" % breakpoint.condition)


#write the debugger; statements to the document before save
class WriteDebug(sublime_plugin.TextCommand):
    def run(self, edit):
        #iterate breakpoints and write debugger; statments
        breakpointList = get_breakpointList(self.view)
        for id in breakpointList.breakpoints:
            breakpoint = breakpointList.breakpoints[id]
            if breakpoint.enabled:

                point = self.view.text_point(int(breakpoint.lineNum)-1, 0)
                lineText = self.view.substr(self.view.line(point))

                #find offset of first non-whitespace character
                #clever trick from http://stackoverflow.com/a/2378988
                offset = len(lineText) - len(lineText.lstrip())

                point = self.view.text_point(int(breakpoint.lineNum)-1, offset)
                #insert the debugger statement
                self.view.insert(edit, point, breakpoint.debugger)


#remove debugger; statements from the document after save
class ClearDebug(sublime_plugin.TextCommand):
    def run(self, edit):
        breakpointList = get_breakpointList(self.view)
        for id in breakpointList.breakpoints:
            breakpoint = breakpointList.breakpoints[id]
            if breakpoint.enabled:
                line = self.view.line(self.view.text_point(breakpoint.lineNum-1, 0))
                dedebugged = self.view.substr(line)
                dedebugged = re.sub(r'%s' % re.escape(breakpoint.debugger), '', dedebugged)
                self.view.replace(edit, line, dedebugged)


#listen for events and call necessary functions
class EventListener(sublime_plugin.EventListener):

    #a dict containing the number of lines from the last update. viewId is the key
    #used to figure out if lines have been added or removed
    numLines = {}
    #kinda hacky list of breakpoint id's. when a status is added to the status bar
    #it needs to be removed later. this is a list of statuses to be removed. should
    #be emptied out pretty frequently
    setStatuses = []

    def on_modified(self, view):
        if not should_track_view(view):
            return

        viewId = str(view.id())

        #fix for https://github.com/rDr4g0n/JsDebuggr/issues/10
        if view.is_scratch():
            printl("JsDebuggr: view is marked as scratch. setting scratch to false.")
            view.set_scratch(False)

        #if the number of lines hasn't been recorded, then on_load must
        #not have been triggered, so trigger it
        if not viewId in self.numLines:
            printl("JsDebuggr: on_load wasn't fired. firing it.")
            self.on_load(view)
            if not should_track_view(view):
                return

        breakpointList = get_breakpointList(view)

        #determine how many lines are in this view
        currNumLines = view.rowcol(view.size())[0] + 1
        # if it doesnt match numLines, evaluate where the lines were inserted/removed
        if currNumLines != self.numLines[viewId]:
            added = currNumLines - self.numLines[viewId]
            printl("JsDebuggr: omg %i lines added!" % added)
            #use the cursor position to guess where the lines were inserted/removed
            #NOTE - this only supports single cursor operations
            #cursorLine = view.rowcol(view.sel()[0].a)[0] + 1
            #TODO - shift method might need a refactor/rename
            breakpointList.shift()

            #update new number of lines
            self.numLines[viewId] = currNumLines

    def on_pre_save(self, view):
        if not should_track_view(view):
            return

        #insert debugger; statments
        printl("JsDebuggr: inserting debuggers")
        view.run_command("write_debug")

    def on_post_save(self, view):
        if not should_track_view(view):
            #the filename may have changed, so this view may need
            #to be tracked
            if should_track_view(view, True):
                self.on_load(view)
            return

        printl("JsDebuggr: clearing debuggers")
        view.run_command("clear_debug")
        #fix for https://github.com/rDr4g0n/JsDebuggr/issues/10
        printl("JsDebuggr: marking view as scratch")
        view.set_scratch(True)

    def on_load(self, view):
        if not should_track_view(view):
            return

        viewId = str(view.id())

        #if the number of lines has not been recorded, record it
        if not viewId in self.numLines:
            self.numLines[viewId] = view.rowcol(view.size())[0] + 1
            printl("JsDebuggr: setting numlines to %i" % self.numLines[viewId])
        #force create breakpoint list

        breakpointList = get_breakpointList(view)

        debug_statement = DEBUG_STATEMENT
        conditional_begin_marker = CONDITIONAL_BEGIN_MARKER
        conditional_end_marker = CONDITIONAL_END_MARKER

        if AUTOSCAN_ON_LOAD:
            #scan the doc for debugger; statements. if found, make em into
            #breakpoints and remove the statement
            existingDebuggers = view.find_all(r'%s' % re.escape(debug_statement))
            printl("JsDebuggr: found %i existing debugger statements" % len(existingDebuggers))
            for region in existingDebuggers:
                condition = None
                #TODO - this whole conditional check is very ugly and hacky. there
                #       has to be a smarter way to do it... prolly a simple regex lawl
                lineText = view.substr(view.line(region))
                conditionalBegin = re.search(r'%s' % re.escape(conditional_begin_marker), lineText)
                if conditionalBegin:
                    #this is a conditional break, so get the condition
                    conditionalEnd = re.search(r'%s' % re.escape(conditional_end_marker), lineText)
                    condition = lineText[conditionalBegin.end(0): conditionalEnd.start(0)]
                    printl("JsDebuggr: existing debugger is a conditional: '%s'" % condition)

                breakpointList.add(view.rowcol(region.a)[0] + 1, condition)

            #clear any debugger; statements from the doc
            view.run_command("clear_debug")

    #determines if the selected line has a breakpoint, and if so
    #does stuff related to that berakpoint
    def on_selection_modified(self, view):
        if not should_track_view(view):
            return

        breakpointList = get_breakpointList(view)
        cursorLine = view.rowcol(view.sel()[0].a)[0] + 1
        breakpoint = breakpointList.get(cursorLine)

        #TODO - if this is a breakpoint, take note so that is_visible() can
        #       determine which context menu items to show
        #if this breakpoint is a conditional, show the condition in the
        #status bar
        if breakpoint and breakpoint.condition:
            view.set_status(breakpoint.id, "JsDebuggr Condition: `%s`" % breakpoint.condition)
            self.setStatuses.append(breakpoint.id)
        else:
            #TODO - this whole setStatuses list seems kinda hacky...
            for id in self.setStatuses:
                view.erase_status(id)
            self.setStatuses = []
