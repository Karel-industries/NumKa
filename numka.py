#!/usr/bin/env python

import argparse
import dataclasses
import os

# == compiler globals ==

version = "v0.3.0"

source_file_compiled = {}
import_paths = []

output_source = ""
defined_fn_prototypes = {}
instaciated_fns = {}

builtin_dialects = {
    "PyKarel/Kvm": [
        {
            "step": "STEP",
            "left": "LEFT",
            "pick": "PICK",
            "place": "PLACE",
            "stop": "STOP",
        },
        {
            "end",
            "until",
            "repeat"
        },
        { # codegen only keywords
            "end": "END",
            "if": "IF",
            "is": "IS",
            "not": "ISNOT",
            "else": "END, ELSE",
            "while": "UNTIL",
            "for": "REPEAT",
            "for-suffix": "-TIMES",

            "wall": "WALL",
            "flag": "FLAG",
            "home": "HOME",
            "north": "NORTH",
            "south": "SOUTH",
            "east": "EAST",
            "west": "WEST",
        }
    ],

    "VisK99": [
        { # dialect exposed keywords
            "step": "KROK",
            "left": "VLEVO-VBOK",
            "pick": "ZVEDNI",
            "place": "POLOŽ",
            "stop": "STOP",
        },
        { # reserved keywords
            "konec",
            "dokud",
            "opakuj",
        },
        { # codegen only keywords
            "end": "KONEC",
            "if": "KDYŽ",
            "is": "JE",
            "not": "NENÍ",
            "else": "KONEC, JINAK",
            "while": "DOKUD",
            "for": "OPAKUJ",
            "for-suffix": "-KRÁT",

            "wall": "ZEĎ",
            "flag": "ZNAČKA",
            "home": "DOMOV",
            "north": "SEVER",
            "south": "JIH",
            "east": "VÝCHOD",
            "west": "ZÁPAD",
        }
    ],
}

# note: filled by the correct dialect on init
builtin_fns = {}
builtit_reserved = set()
builtin_cg_keywords = {}

# == compiler utils ==

bold_escape = "\x1b[1m"
error_escape = f"{bold_escape}\x1b[31m"
warning_escape = f"{bold_escape}\x1b[33m"
reset_escape = "\x1b[0m"

warning_level = 1
log_source_view_size = 2

class CompileError(Exception):
    def __init__(self, message, src_file: str, line_index: int, src: list) -> None:
        super().__init__(message)

        self.message = message
        self.src_file = src_file
        self.src = src
        self.line_index = line_index

last_status = ""

def status_print(file: str):
    global last_status
    last_status = file

    print(f"\x1b[1K\r{bold_escape}Compiling:{reset_escape} {file}", end="")
    # print(f"{bold_escape}Compiling:{reset_escape} {file}", end="\n")

def reset_status():
    print()
    status_print(last_status)

def error_print(src_file: str, error_message: str, line_index: int, src: list):
    print(f"\n\n{error_escape}error{reset_escape}: {error_message} at \"{src_file}\":{line_index + 1}")
    
    max_digits = len(str(line_index + log_source_view_size + 1))

    for i in range((-log_source_view_size), log_source_view_size + 1):
        j = line_index + i
        
        if j < 0 or j > len(src) - 1:
            continue
        
        print(f"{bold_escape + error_escape if i == 0 else ''}  {j + 1:0={max_digits}}:  {src[j]}{reset_escape}")

    print()

def warn_print(src_file: str, warning_message: str, line_index: int, src: list):
    if warning_level == 2:
        raise CompileError(warning_message, src_file, line_index, src)
    elif warning_level == 0:
        return

    print(f"\n\n{warning_escape}warning{reset_escape}: {warning_message} at \"{src_file}\":{line_index + 1}")
    
    max_digits = len(str(line_index + log_source_view_size))

    for i in range((-log_source_view_size), log_source_view_size + 1):
        j = line_index + i
        
        if j < 0 or j > len(src) - 1:
            continue
        
        print(f"{bold_escape + warning_escape if i == 0 else ''}  {j + 1:0={max_digits}}:  {src[j]}{reset_escape}")
    
    reset_status()

# == source asts ==

@dataclasses.dataclass(kw_only=True)
class CallableAst:
    name: str
    comp_name: str

@dataclasses.dataclass(kw_only=True)
class FnPrototypeAst:
    name: str
    line_of_definition: int
    ending_line_of_definition: int

    template_args: tuple
    
    # if matches top-level requrements (no templates, no commit) it will get compiled into output even when never used
    top_level_implicit_usage: bool
    is_slice_valid: bool

    fn_src: str

    src: list
    src_file: str

@dataclasses.dataclass(kw_only=True)
class FnInstanceAst:
    name: str
    comp_name: str

    owning_lambdas: list = dataclasses.field(default_factory=list)
    tracked_stack_slices: list = dataclasses.field(default_factory=list)

    compiled_segments: list[str] = dataclasses.field(default_factory=list[str])

    commit_fn: CallableAst | None = None
    instance_template_args: tuple
    inherited_template_arg_values: tuple = dataclasses.field(default_factory=tuple)
    inherited_template_args: tuple = dataclasses.field(default_factory=tuple)

@dataclasses.dataclass(kw_only=True)
class CallLocationAst:
    caller_fn_name: str
    callee_fn_name: str

    template_arg_values: tuple
    inherited_template_arg_values: tuple = dataclasses.field(default_factory=tuple)

    inherited_template_args: tuple = dataclasses.field(default_factory=tuple)

    callee_commit_dest_fn: CallableAst | None

    src: list[str]
    src_file: str
    caller_line_index: int

# == compiler ==

def parse_template_args(src: list, src_file: str, src_line: int, call_exp: str, args: argparse.Namespace) -> tuple[tuple, int]:
    # find template args clousure begining
    i = 0

    while i < len(call_exp):
        c = call_exp[i]

        if c == ')':
            raise CompileError("syntax error - unexpected \')\' before \'(\' in a call expression", src_file, src_line, src)

        if c == '(':
            break

        i += 1

    if i == len(call_exp):
        # no templates args used
        return (tuple(), 0)
    
    # find template args clousure end
    i += 1
    j = i

    template_args = []
    clousure_depth = 1

    while j < len(call_exp):
        c = call_exp[j]

        if c == '(':
            clousure_depth += 1
            
            # raise CompileError("syntax error - unexpected \'(\' after template expression", src_file, src_line, src)

        elif c == ')':
            clousure_depth -= 1

            if clousure_depth == 0:
                template_args.append(call_exp[i:j])
                i = j + 1

                break
        
        elif c == ',' and clousure_depth == 1:
            template_args.append(call_exp[i:j])
            i = j + 1

        j += 1
    
    if j == len(call_exp):
        raise CompileError("unexpected end of file - template args expression never closed", src_file, src_line, src)

    # cleanup template args

    for i in range(len(template_args)):
        template_args[i] = template_args[i].strip()

    if len(template_args) == 1 and template_args[0].strip() == '':
        # alternate syntax for no template args
        return (tuple(), j)

    for i, arg in enumerate(template_args):
        arg = arg.strip()

        if arg == '':
            raise CompileError(f"syntax error - missing template argument at position {i + 1}", src_file, src_line, src)

    return (tuple(template_args), j)

def parse_contition(src: list, src_file: str, src_line: int, cond_exp: str, args: argparse.Namespace) -> tuple[str, int]:
    size_read = 0
    orig_cond_exp = cond_exp
    
    if cond_exp.startswith("is_"):
        cond_exp = cond_exp[3:]
        size_read += 3
        invert_prefix = f"{builtin_cg_keywords['is']} "
    elif cond_exp.startswith("not_"):
        cond_exp = cond_exp[4:]
        size_read += 4
        invert_prefix = f"{builtin_cg_keywords['not']} "
    else:
        raise CompileError("syntax error - condition must start with 'is_' or 'not_'", src_file, src_line, src)

    if cond_exp.startswith("wall "):
        return (invert_prefix + f"{builtin_cg_keywords['wall']}", 5 + size_read)
    elif cond_exp.startswith("flag "):
        return (invert_prefix + f"{builtin_cg_keywords['flag']}", 5 + size_read)
    elif cond_exp.startswith("home "):
        return (invert_prefix + f"{builtin_cg_keywords['home']}", 5 + size_read)
    elif cond_exp.startswith("north "):
        return (invert_prefix + f"{builtin_cg_keywords['north']}", 6 + size_read)
    elif cond_exp.startswith("south "):
        return (invert_prefix + f"{builtin_cg_keywords['south']}", 6 + size_read)
    elif cond_exp.startswith("east "):
        return (invert_prefix + f"{builtin_cg_keywords['east']}", 5 + size_read)
    elif cond_exp.startswith("west "):
        return (invert_prefix + f"{builtin_cg_keywords['west']}", 5 + size_read)
    else:
        raise CompileError(f"syntax error - unknown condition \"{orig_cond_exp.strip()}\"", src_file, src_line, src)

def parse_fn(src: list, src_file: str, define_line_index: int, lambda_owner: FnInstanceAst | None, args: argparse.Namespace) -> FnPrototypeAst:
    tem_args, tem_end = parse_template_args(src, src_file, define_line_index, src[define_line_index], args)
    
    is_slice = False
    if lambda_owner == None:
        fn_name = src[define_line_index].split('//', 1)[0].strip()[3:].rstrip("{").strip()

        if fn_name.endswith(" slicing"):
            is_slice = True
            fn_name = fn_name[:-8].strip()

        fn_name = fn_name.split('(', 1)[0].strip()

        if ' ' in fn_name:
            raise CompileError("syntax error - fn name cannot contain spaces", src_file, define_line_index, src)
        elif fn_name in builtit_reserved or fn_name.upper() in builtin_fns.values() or fn_name.upper() in builtin_cg_keywords.values():
            raise CompileError(f"\"{fn_name}\" is a reserved keyword by karel-lang", src_file, define_line_index, src)
    else:
        fn_name = f"{lambda_owner.name}_lambda_n{len(lambda_owner.owning_lambdas)}"
        is_slice = not lambda_owner.commit_fn == None # parent is commiting -> is a slice valid fn

    # find end of fn
    
    end_line = -1
    clousure_depth = 0

    for i, line in enumerate(src[define_line_index:]):
        for j, char in enumerate(line):
            if char == '{':
                clousure_depth += 1

            elif char == '}':
                clousure_depth -= 1
                
                if clousure_depth == 0:
                    end_line = i + define_line_index

                    if not j + 1 == len(line.split('//', 1)[0].strip()) and lambda_owner == None:
                        raise CompileError("syntax error - expected a new line after fn final \'}\'", src_file, i + define_line_index, src) 

                    break
                elif clousure_depth < 0:
                    raise CompileError("syntax error - unexpected '}' before any '{'", src_file, i + define_line_index, src)
        
        if not end_line == -1:
            break
    
    if end_line == -1:
        raise CompileError(f"syntax error - fn \"{fn_name}\" never closed (did you forget a \'{'}'}\'?)", src_file, len(src) - 1, src)

    # create fn ast

    if fn_name in defined_fn_prototypes:
        raise CompileError(f"redefinition of fn \"{fn_name}\" first defined at \"{defined_fn_prototypes[fn_name].src_file}\":{defined_fn_prototypes[fn_name].line_of_definition + 1}", src_file, define_line_index, src)

    # strip fn source for compile stage

    fn_src = src[define_line_index:end_line + 1]
    for i in range(len(fn_src)):
        l = fn_src[i]

        # strip comments
        l = l.split('//', 1)[0]

        l = l.strip()

        fn_src[i] = l + '\n'

    # test for top-level implicit usage

    inline_fn_src = ''.join(fn_src)
    implicit_usage = True

    # must not use templates to be implicitly used
    if not len(tem_args) == 0:
        implicit_usage = False

    # must not be a slicing fn to be implicitly used
    elif is_slice:
        implicit_usage = False

    # lambdas can contain inherited template args which we cannot check here
    # lambdas are always used "explicitly" anyway
    elif not lambda_owner == None:
        implicit_usage = False

    fn = FnPrototypeAst(name=fn_name, fn_src=inline_fn_src, src=src, src_file=src_file, ending_line_of_definition=end_line, line_of_definition=define_line_index, template_args=tem_args, top_level_implicit_usage=implicit_usage, is_slice_valid=is_slice)
    defined_fn_prototypes[fn_name] = fn

    return fn

def gen_comp_name(fn_proto: FnPrototypeAst, call_loc: CallLocationAst, seg_index: int) -> str:
    if not args.g:
        return fn_proto.name + ('' if seg_index == 0 else f"_seg{seg_index}") + f"<ch{hash(call_loc.callee_commit_dest_fn.comp_name) if not call_loc.callee_commit_dest_fn is None else '-none'}-th{hash(call_loc.template_arg_values + call_loc.inherited_template_arg_values) if len(call_loc.template_arg_values) + len(call_loc.inherited_template_arg_values) else '-none'}>"
    else:
        return fn_proto.name + ('' if seg_index == 0 else f"_seg{seg_index}") + f"<commit-loc={call_loc.callee_commit_dest_fn.comp_name if not call_loc.callee_commit_dest_fn is None else 'none'}|template-args={call_loc.template_arg_values}{f'+inherited={call_loc.inherited_template_arg_values}' if len(call_loc.inherited_template_arg_values) > 0 else ''}>".replace(' ', '')

# returns a precompiled FnInstanceAst if it has already been compiled with the same template args and commit fn 
def compile_fn(fn_proto: FnPrototypeAst, call_loc: CallLocationAst, args: argparse.Namespace) -> FnInstanceAst:
    i = 0
    line_index = fn_proto.line_of_definition

    # status_print(f"{fn_proto.name} in {fn_proto.src_file}")

    # import time
    # time.sleep(.05)

    # create fn instance ast

    comp_name = gen_comp_name(fn_proto, call_loc, 0)

    if fn_proto.top_level_implicit_usage:
        # fns with implicit usage are by definition the only fn with that name
        # no extra strings are required to avoid name collisions

        comp_name = fn_proto.name

    # return FnInstanceAst if already compiled an instance with the same template set and commit fn
    if comp_name in instaciated_fns:
        return instaciated_fns[comp_name]

    fn = FnInstanceAst(name=fn_proto.name, comp_name=comp_name, commit_fn=call_loc.callee_commit_dest_fn, instance_template_args=call_loc.template_arg_values, inherited_template_arg_values=call_loc.inherited_template_arg_values, inherited_template_args=call_loc.inherited_template_args)
    instaciated_fns[comp_name] = fn

    # define function in output source

    current_comp_segment = ""
    current_comp_segment_depth = 1

    current_comp_segment_index = 0
    next_comp_segment_index = 0

    comp_segment_stack = []

    block_clousure_depth = 1

    # slice order tracking
    slice_stack_scopes = []
    poped_stack_slices = []

    # used for validating else statements
    is_last_end_if = {}

    current_comp_segment = ''.join((current_comp_segment, fn.comp_name, '\n'))

    # instantiate template args

    if not len(fn_proto.template_args) == len(call_loc.template_arg_values):
        raise CompileError(f"incorrect number of template args for fn \"{fn_proto.name}\", expected {len(fn_proto.template_args)}, got {len(call_loc.template_arg_values)}", call_loc.src_file, call_loc.caller_line_index, call_loc.src)

    to_replace = fn_proto.template_args + call_loc.inherited_template_args
    to_insert = call_loc.template_arg_values + call_loc.inherited_template_arg_values

    fn_src = fn_proto.fn_src
    for i, arg in enumerate(to_replace):
        fn_src = fn_src.replace('[' + arg + ']', to_insert[i])

    # parse and compile fn segments

    while fn_src[i] != '{':
        i += 1
    i += 1

    acc = ""

    while i < len(fn_src):
        c = fn_src[i]

        if c == '\n':
            line_index += 1

            if not len(acc) == 0 and not acc[-1] == ' ':
                acc += ' '
            
            i += 1
            continue
        elif c.strip() == '':
            if not len(acc) == 0 and not acc[-1] == ' ':
                acc += ' '
            
            i += 1
            continue
        elif c == '[':
            warn_print(fn_proto.src_file, f"unresolved template target in fn \"{fn_proto.name}\" called by fn \"{call_loc.caller_fn_name}\" (did you forget to define it in template args?)", line_index, fn_proto.src)

            start_line_index = line_index
            while i < len(fn_src):
                c = fn_src[i]

                if c == '\n':
                    line_index += 1
                elif c == ']':
                    break

                i += 1

            if not c == ']':
                raise CompileError("syntax error - unresolved template target never closed, expected \']\'", fn_proto.src_file, start_line_index, fn_proto.src)

        elif c == '{':
            # parse block

            block_clousure_depth += 1

            if '=' in acc:
                # TODO: slice assigment
                pass
            elif acc.startswith("if "):
                acc = acc[3:]

                cond = parse_contition(fn_proto.src, fn_proto.src_file, line_index, acc, args)
                acc = acc[cond[1]:]

                if not acc.strip() == '':
                    raise CompileError("syntax error - expected a \'{\' after an if statement", fn_proto.src_file, line_index, fn_proto.src)

                current_comp_segment = ''.join((current_comp_segment, '   ' * current_comp_segment_depth, f"{builtin_cg_keywords['if']} {cond[0]}\n"))
                is_last_end_if[current_comp_segment_depth] = True
                current_comp_segment_depth += 1

            elif acc.startswith("else"): # note: no suffixed space because else keyword doesn't have a condition
                acc = acc[4:]

                # check that the last output line is an end of an if block
                if not current_comp_segment_depth in is_last_end_if or not is_last_end_if[current_comp_segment_depth] or (not len(current_comp_segment) > len(builtin_cg_keywords['end']) + 1 or not current_comp_segment[-(len(builtin_cg_keywords['end']) + 1):] == f"{builtin_cg_keywords['end']}\n"):
                    raise CompileError("syntax error - else statements can be only defined after an if", fn_proto.src_file, line_index, fn_proto.src)

                if not acc.strip() == '':
                    raise CompileError("syntax error - expected a \'{\' after an else statement", fn_proto.src_file, line_index, fn_proto.src)

                # remove last 'END\n' and reopen the (empty) else block
                current_comp_segment = current_comp_segment[:-(len(builtin_cg_keywords['end']) + 1) - len('   ' * current_comp_segment_depth)]
                is_last_end_if[current_comp_segment_depth] = False
                current_comp_segment_depth += 1

            elif acc.startswith("while "):
                acc = acc[6:]

                cond = parse_contition(fn_proto.src, fn_proto.src_file, line_index, acc, args)
                acc = acc[cond[1]:]

                if not acc.strip() == '':
                    raise CompileError("syntax error - expected a \'{\' after a while statement", fn_proto.src_file, line_index, fn_proto.src)

                current_comp_segment = ''.join((current_comp_segment, '   ' * current_comp_segment_depth, f"{builtin_cg_keywords['while']} {cond[0]}\n"))
                is_last_end_if[current_comp_segment_depth] = False
                current_comp_segment_depth += 1

            elif acc.startswith("for "):
                acc = acc[4:]

                try:
                    count = int(acc, base=0)
                    acc = acc[len(str(count)):]
                except ValueError:
                    raise CompileError(f"for loop count \"{acc.strip()}\" is not convertible to an integer", fn_proto.src_file, line_index, fn_proto.src)

                if not acc.strip() == '':
                    raise CompileError("syntax error - expected a \'{\' after a for statement", fn_proto.src_file, line_index, fn_proto.src)

                if count > args.max_loop_count:
                    warn_print(fn_proto.src_file, f"for loop count {count} is greater than the safe maximum of {args.max_loop_count}", line_index, fn_proto.src)

                current_comp_segment = ''.join((current_comp_segment, '   ' * current_comp_segment_depth, f"{builtin_cg_keywords['for']} {count}{builtin_cg_keywords['for-suffix']}\n"))
                is_last_end_if[current_comp_segment_depth] = False
                current_comp_segment_depth += 1

            elif acc.startswith("fn "):
                raise CompileError("syntax error - fn definitions are not allowed inside fn bodies (did you forget a \'}\'?)", fn_proto.src_file, line_index, fn_proto.src)
            else:
                # parse lambda for this fn instance

                fn_name = f"{fn.name}_lambda_n{len(fn.owning_lambdas)}"

                if fn_name in defined_fn_prototypes:
                    lambda_proto =  defined_fn_prototypes[fn_name] 
                else:
                    lambda_proto = parse_fn(fn_proto.src, fn_proto.src_file, line_index, fn, args)

                # offset to lambdas end

                clousure_depth = 0
                while i < len(fn_src):
                    char = fn_src[i]
                    
                    if char == '\n':
                        line_index += 1

                    if char == '{':
                        clousure_depth += 1

                    elif char == '}':
                        clousure_depth -= 1

                        if clousure_depth == 0:
                            break
                    
                    i += 1
                i += 1

                # parse out the template instanciation args

                l_acc = ''

                while i < len(fn_src):
                    c = fn_src[i]

                    if c == '\n':
                        line_index += 1
                        l_acc += ' '

                        if not len(l_acc) == 0 and not l_acc[-1] == ' ':
                            l_acc += ' '
                    elif c.strip() == '':
                        if not len(l_acc) == 0 and not l_acc[-1] == ' ':
                            l_acc += ' '
                    elif c == ';':
                        if '(' in l_acc and not ')' in l_acc:
                            raise CompileError("syntax error - unexpected \';\' inside a template args closure", fn_proto.src_file, line_index, fn_proto.src)

                        break
                    else:
                        if not '(' in l_acc and not c == '(':
                            raise CompileError("syntax error - expected a \';\' after a lambda definition", fn_proto.src_file, line_index, fn_proto.src)

                        l_acc += c
                    
                    i += 1

                # compile lambda fn instance
                tem_args, read_size = parse_template_args(fn_proto.src, fn_proto.src_file, line_index, l_acc, args)

                if not read_size == 0:
                    l_acc = l_acc[read_size + 1:]
                else:
                    l_acc = l_acc[1:]
                
                l_acc = l_acc.strip()

                if not l_acc == '':
                    raise CompileError("syntax error - expected a \';\' after a lambda definition", fn_proto.src_file, line_index, fn_proto.src)

                lambda_call_loc = CallLocationAst(
                    caller_fn_name=fn_proto.name,
                    callee_fn_name=lambda_proto.name,
                    template_arg_values=tem_args,
                    inherited_template_arg_values=call_loc.template_arg_values + fn.inherited_template_arg_values,
                    inherited_template_args=fn_proto.template_args + fn.inherited_template_args,
                    callee_commit_dest_fn=call_loc.callee_commit_dest_fn, # lambdas can commit parents pushes
                    src=fn_proto.src,
                    src_file=fn_proto.src_file,
                    caller_line_index=line_index
                )

                # note: includes callers templates in the template hash, as parents template args can affect a child lambda
                lambda_fn_instance = compile_fn(lambda_proto, lambda_call_loc, args)

                # call lambda
                current_comp_segment = ''.join((current_comp_segment, '   ' * current_comp_segment_depth, f"{lambda_fn_instance.comp_name}\n"))

                fn.owning_lambdas.append(lambda_fn_instance)
                block_clousure_depth -= 1

            acc = ""
        
        elif c == '}':
            if not acc.strip() == '':
                raise CompileError("syntax error - unexpected expression before '}' (did you forget a ';'?)", fn_proto.src_file, line_index, fn_proto.src)

            # end block
            acc = ""

            current_comp_segment_depth -= 1
            
            if not current_comp_segment_depth in is_last_end_if or not is_last_end_if[current_comp_segment_depth]:
                current_comp_segment = ''.join((current_comp_segment, '   ' * current_comp_segment_depth, f"{builtin_cg_keywords['end']}\n"))
            else:
                current_comp_segment = ''.join((current_comp_segment, '   ' * current_comp_segment_depth, f"{builtin_cg_keywords['else']}\n", '   ' * current_comp_segment_depth, f"{builtin_cg_keywords['end']}\n"))

            block_clousure_depth -= 1
            if block_clousure_depth == 0:
                # ending fn instance

                if not len(slice_stack_scopes) == 0:
                    raise CompileError(f"stack slice(s) {slice_stack_scopes} were not poped before ending scope! No tracked slices must exist at the end of a scope", fn_proto.src_file, line_index, fn_proto.src) 

                if len(fn.compiled_segments) > current_comp_segment_index:
                    fn.compiled_segments[current_comp_segment_index] = ''.join((current_comp_segment, '\n'))
                else:
                    fn.compiled_segments.append(''.join((current_comp_segment, '\n')))

                break

        elif c == ';':
            # parse expression

            acc = acc.strip()

            if acc == "++":
                current_comp_segment = ''.join((current_comp_segment, '   ' * current_comp_segment_depth, f"{builtin_fns['place']}\n"))
            elif acc == "--":
                current_comp_segment = ''.join((current_comp_segment, '   ' * current_comp_segment_depth, f"{builtin_fns['pick']}\n"))
            elif acc == "":
                pass
            elif acc in builtin_fns:
                current_comp_segment = ''.join((current_comp_segment, '   ' * current_comp_segment_depth, f"{builtin_fns[acc]}\n"))
            elif acc.startswith("no_op"):
                if not acc.strip() == "no_op":
                    raise CompileError(f"syntax error - expected a ';' after a no_op keyword", fn_proto.src_file, line_index, fn_proto.src)

                pass # no_op does a no-op
            elif acc.startswith("recall"):
                # if '(' in acc and not ')' in acc:
                #     raise CompileError("syntax error - unexpected \';\' inside a template args closure", fn_proto.src_file, line_index, fn_proto.src)

                tem_args, size_read = parse_template_args(fn_proto.src, fn_proto.src_file, line_index, acc, args)
                
                if size_read == 0:
                    acc = acc[6:]
                else:
                    acc = acc[size_read + 1:]

                acc = acc.strip()

                if not acc == '':
                        raise CompileError(f"syntax error - expected a ';' after a recall keyword", fn_proto.src_file, line_index, fn_proto.src)

                # recompile fn with possibly new template args
                recall_loc = CallLocationAst(
                    caller_fn_name=fn_proto.name, 
                    callee_fn_name=fn_proto.name,
                    template_arg_values=call_loc.template_arg_values if len(tem_args) == 0 else tem_args,
                    inherited_template_arg_values=fn.inherited_template_arg_values,
                    inherited_template_args=fn.inherited_template_args,
                    callee_commit_dest_fn=call_loc.callee_commit_dest_fn,
                    src=fn_proto.src,
                    src_file=fn_proto.src_file,
                    caller_line_index=line_index
                )

                recall_fn_instance = compile_fn(fn_proto, recall_loc, args)

                if current_comp_segment_depth == 1:
                    warn_print(fn_proto.src_file, f"recall most likely causes an infinite loop", line_index, fn_proto.src)

                current_comp_segment = ''.join((current_comp_segment, '   ' * current_comp_segment_depth, recall_fn_instance.comp_name, '\n'))
            elif acc.startswith("commit"):
                if not fn_proto.is_slice_valid:
                    raise CompileError(f"cannot use the commit keyword inside a non-slice fn (see numka slice fn docs)", fn_proto.src_file, line_index, fn_proto.src)

                if not call_loc.callee_commit_dest_fn is None:
                    acc = acc[6:].strip()

                    if not acc == '':
                        raise CompileError(f"syntax error - expected a ';' after a commit keyword", fn_proto.src_file, line_index, fn_proto.src)

                    # commit by calling target fn

                    current_comp_segment = ''.join((current_comp_segment, '   ' * current_comp_segment_depth, call_loc.callee_commit_dest_fn.comp_name, '\n'))
                else:
                    warn_print(fn_proto.src_file, f"commit keyword used while not pushing a stack slice, called from fn \"{call_loc.caller_fn_name}\"", line_index, fn_proto.src)

            elif '=' in acc:
                exp = acc.split('=', 1)

                slice_name = exp[0].strip()

                if ' ' in slice_name:
                    raise CompileError("syntax error - stack slice names cannot contain spaces", fn_proto.src_file, line_index, fn_proto.src)

                acc = exp[1].strip()

                if acc.startswith('push '):
                    acc = acc[5:]

                    if '(' in acc and not ')' in acc:
                        raise CompileError("syntax error - unexpected \';\' inside a template args closure", fn_proto.src_file, line_index, fn_proto.src)

                    tem_args, size_read = parse_template_args(fn_proto.src, fn_proto.src_file, line_index, acc, args)

                    if size_read == 0:
                        if len(acc.split(' ', 1)) == 2:
                            raise CompileError(f"syntax error - expected a \';\' after a push fn call", fn_proto.src_file, line_index, fn_proto.src)
                        
                        acc = acc.split(' ', 1)[0]
                    else:
                        if not acc[size_read + 1:].strip() == '':
                            raise CompileError(f"syntax error - expected a \';\' after a push fn call", fn_proto.src_file, line_index, fn_proto.src)

                        acc = acc.split('(', 1)[0].strip()

                    if slice_name in slice_stack_scopes:
                        raise CompileError(f"stack slice name \"{acc}\" already in use", fn_proto.src_file, line_index, fn_proto.src)

                    if not current_comp_segment_depth == 1:
                        raise CompileError(f"for now, stack slices can be only used on the root scope (outside of if, while, for, etc.)", fn_proto.src_file, line_index, fn_proto.src)

                    # gen next segment comp_name and use it as commit dest fn
                    comp_segment_stack.append(current_comp_segment_index)
                    old_segment_index = current_comp_segment_index

                    next_comp_segment_index += 1
                    current_comp_segment_index = next_comp_segment_index

                    comp_name = gen_comp_name(fn_proto, call_loc, current_comp_segment_index)

                    commit_loc = CallableAst(
                        name=fn_proto.name + f"[segment:{current_comp_segment_index}]",
                        comp_name=comp_name
                    )

                    # push fn callee
                    callee_fn = defined_fn_prototypes.get(acc)

                    if callee_fn is None:
                        raise CompileError(f"call to an undefined push fn \"{acc}\"", fn_proto.src_file, line_index, fn_proto.src)

                    elif not callee_fn.is_slice_valid:
                        raise CompileError(f"cannot push a non-slice fn \"{acc}\"", fn_proto.src_file, line_index, fn_proto.src)

                    push_loc = CallLocationAst(
                        caller_fn_name=fn_proto.name, 
                        callee_fn_name=acc,
                        template_arg_values=tem_args,
                        callee_commit_dest_fn=commit_loc,
                        src=fn_proto.src,
                        src_file=fn_proto.src_file,
                        caller_line_index=line_index
                    )

                    push_fn = compile_fn(callee_fn, push_loc, args)

                    current_comp_segment = ''.join((current_comp_segment, '   ' * current_comp_segment_depth, push_fn.comp_name, '\n'))
                    slice_stack_scopes.insert(0, slice_name)
                    
                    if slice_name in poped_stack_slices:
                        poped_stack_slices.remove(slice_name)

                    # split fn segments
                    
                    if len(fn.compiled_segments) > old_segment_index: # unfinished, will be continued after pop
                        fn.compiled_segments[old_segment_index] = current_comp_segment
                    else:
                        fn.compiled_segments.append(current_comp_segment)
                    
                    current_comp_segment = ""
                    current_comp_segment = ''.join((comp_name, '\n'))

                    current_comp_segment_depth = 1

                else:
                    raise CompileError("syntax error - stack slice assignment must use the \'push\' keyword", fn_proto.src_file, line_index, fn_proto.src)

            elif acc.startswith('pop '):
                acc = acc[4:].strip()

                if ' ' in acc:
                    raise CompileError("syntax error - expected \';\' after a pop", fn_proto.src_file, line_index, fn_proto.src)

                if acc in poped_stack_slices:
                    raise CompileError(f"stack slice \"{acc}\" already poped", fn_proto.src_file, line_index, fn_proto.src)

                elif len(slice_stack_scopes) == 0 or not acc in slice_stack_scopes:
                    raise CompileError(f"unknown stack slice \"{acc}\"", fn_proto.src_file, line_index, fn_proto.src)

                elif not slice_stack_scopes[0] == acc:
                    raise CompileError(f"only the last pushed stack slice (here it's slice \"{slice_stack_scopes[0]}\") can be poped", fn_proto.src_file, line_index, fn_proto.src)

                if not current_comp_segment_depth == 1:
                        raise CompileError(f"for now, stack slices can be only used on the root scope (outside of if, while, for, etc.)", fn_proto.src_file, line_index, fn_proto.src)

                slice_stack_scopes.pop(0)
                poped_stack_slices.append(acc)

                # return to push parent fn segment

                if len(fn.compiled_segments) > current_comp_segment_index:
                    fn.compiled_segments[current_comp_segment_index] = ''.join((current_comp_segment, builtin_cg_keywords["end"], "\n\n"))
                else:
                    fn.compiled_segments.append(''.join((current_comp_segment, builtin_cg_keywords["end"], "\n\n")))

                current_comp_segment_index = comp_segment_stack.pop()
                comp_name = gen_comp_name(fn_proto, call_loc, current_comp_segment_index)

                current_comp_segment = fn.compiled_segments[current_comp_segment_index]
                current_comp_segment_depth = 1

            elif acc.startswith("if") or acc.startswith("while") or acc.startswith("for"):
                raise CompileError(f"syntax error - if, while, and for statements do not support bracket-less forms", fn_proto.src_file, line_index, fn_proto.src)
            else:
                if '(' in acc and not ')' in acc:
                    raise CompileError("syntax error - unexpected \';\' inside a template args closure", fn_proto.src_file, line_index, fn_proto.src)

                tem_args, size_read = parse_template_args(fn_proto.src, fn_proto.src_file, line_index, acc, args)

                if size_read == 0:
                    if len(acc.split(' ', 1)) == 2:
                        raise CompileError(f"syntax error - expected a \';\' after a fn call", fn_proto.src_file, line_index, fn_proto.src)
                    
                    acc = acc.split(' ', 1)[0]
                else:
                    if not acc[size_read + 1:].strip() == '':
                        raise CompileError(f"syntax error - expected a \';\' after a fn call", fn_proto.src_file, line_index, fn_proto.src)

                    acc = acc.split('(', 1)[0].strip()

                # fn call
                callee_fn = defined_fn_prototypes.get(acc)

                if callee_fn is None:
                    raise CompileError(f"call to an undefined fn \"{acc}\"", fn_proto.src_file, line_index, fn_proto.src)

                fn_call_loc = CallLocationAst(
                    caller_fn_name=fn_proto.name,
                    callee_fn_name=acc,
                    template_arg_values=tem_args,
                    callee_commit_dest_fn=call_loc.callee_commit_dest_fn if callee_fn.is_slice_valid else None, # can commit for the current fn push (if it's also a slicing fn)
                    src=fn_proto.src,
                    src_file=fn_proto.src_file,
                    caller_line_index=line_index
                )

                callee_fn_instance = compile_fn(callee_fn, fn_call_loc, args)

                current_comp_segment = ''.join((current_comp_segment, '   ' * current_comp_segment_depth, callee_fn_instance.comp_name, "\n"))
            
            acc = ""
        else:
            acc += c

        i += 1
    
    if i == len(fn_src):
        raise CompileError(f"unexpected end of file, fn \"{fn.name}\" never closed (did you forget a \'{'}'}\'?)", fn_proto.src_file, i - 1, fn_proto.src)

    # assemble owned compiled segments in output

    global output_source

    fn.compiled_segments.reverse()
    for seg in fn.compiled_segments:
        output_source = ''.join((output_source, seg.upper()))

    return fn

def compile_source_file(src_file: str, args: argparse.Namespace) -> None:
    source_file_compiled[os.path.realpath(src_file)] = False

    src_file = os.path.normpath(src_file)
    status_print(src_file)

    # parse top-level source asts
    f = open(src_file, 'r')
    src = f.read().split('\n')

    i = 0
    while i < len(src):
        l = src[i].strip()

        # strip comments
        l = l.split('//', 1)[0]

        if l == "":
            i += 1
            continue

        if l.startswith("import "):
            l = l[7:]

            import_file = l.strip()
            found = False

            for path in import_paths:
                path = path + "/" + import_file

                if not os.path.exists(path):
                    continue

                if not os.path.realpath(path) in source_file_compiled:
                    # compile a new source file into output and asts
                    compile_source_file(path, args)
                    found = True

                elif source_file_compiled[os.path.realpath(path)]:
                    found = True

                else:
                    raise CompileError(f"cyclical import of source file \"{import_file}\"", src_file, i, src)

            if not found:
                raise CompileError(f"source file to be imported \"{import_file}\" not found", src_file, i, src)

            # reset status after import
            status_print(src_file)

        elif l.startswith("fn "):
            l = l[3:].lstrip()

            fn = parse_fn(src, src_file, i, None, args)

            if fn.top_level_implicit_usage:
                call_loc = CallLocationAst(
                    caller_fn_name="(top-level)",
                    callee_fn_name=fn.name,
                    template_arg_values=tuple(),
                    callee_commit_dest_fn=None,
                    src=src,
                    src_file=src_file,
                    caller_line_index=fn.line_of_definition
                )

                compile_fn(fn, call_loc, args)

            i += fn.ending_line_of_definition - fn.line_of_definition

        else:
            raise CompileError("syntax error - expression outside of a fn", src_file, i, src)

        i += 1
    
    f.close()
    source_file_compiled[os.path.realpath(src_file)] = True


# == argument parser ==

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='NumKa language transpiler to karel-lang.', prog='numka')

    parser.add_argument('-v', '--version', default=False, action='store_true', help='print compiler version and exit')

    comp_group = parser.add_argument_group('compiler options')

    comp_group.add_argument('-W', choices=['none', 'all', 'err'], default='all', help='warning level')
    comp_group.add_argument('-o', default='out.kl', metavar='output_file', help='output karel-lang file. all source files will be compiled into this file')
    comp_group.add_argument('-I', default=[], metavar='import_dirs', action='append', help='add a directory to import search paths')
    comp_group.add_argument('-vv', default=False, action='store_true', help='enable verbose mode, will print internal asts')
    comp_group.add_argument('-g', default=False, action='store_true', help='enable debug mode, generate human-readable fn names for debugging')

    lang_group = parser.add_argument_group('language options')

    lang_group.add_argument('-lmax-for-loop-count', dest='max_loop_count', default=65535, type=int, help='max safe amount of iterations for a single for loop')
    lang_group.add_argument('-lkarel-lang-dialect', default='PyKarel/Kvm', choices=['VisK99', 'PyKarel/Kvm'], help='enable karel-lang dialect')

    parser.add_argument('source_files', nargs='*', default=[], help='source files to compile')

    args = parser.parse_args()

    # compiler init

    if args.version:
        print(f"NumKa transpiler {version}")
        exit(0)

    if args.W == 'err':
        warning_level = 2
    elif args.W == 'none':
        warning_level = 0

    builtin_fns = builtin_dialects[args.lkarel_lang_dialect][0]
    builtit_reserved = builtin_dialects[args.lkarel_lang_dialect][1]
    builtin_cg_keywords = builtin_dialects[args.lkarel_lang_dialect][2]

    import_paths = ["."]
    for path in args.I:
        import_paths.append(path)

    # start compilation

    try:
        for src_file in args.source_files:
            if src_file in source_file_compiled:
                continue

            compile_source_file(src_file, args)
        
        if args.vv:
            print(defined_fn_prototypes, '\n')
            print(instaciated_fns, '\n')

        o = open(args.o, 'w')
        o.write(output_source)
        o.close()

        print(f"\x1b[1K\rCompiled {bold_escape}{len(source_file_compiled)}{reset_escape} source files into {bold_escape}{args.o}{reset_escape} successfully!")

    except CompileError as e:
        if args.vv:
            print(defined_fn_prototypes, '\n')
            print(instaciated_fns, '\n')

        error_print(e.src_file, e.message, e.line_index, e.src)
        print(f"Compilation {error_escape}failed{reset_escape} in source file {bold_escape}{e.src_file}{reset_escape}!")
        exit(-1)