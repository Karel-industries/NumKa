# NumKa
a high-level language transpiled to karel-lang with support for lambdas, templates and stack semantics.

The NumKa compiler is currently in heavy *WIP*, expect bugs or missing features.

# Usage

To compile NumKa source files, clone this repo and use the `numka.py`
```sh
git clone https://github.com/Karel-industries/NumKa.git numka
cd numka
```

The `numka.py` compiler follows gcc compiler flags where applicable so to compile source file `src.nka` to `out.kl` run
```sh
./numka.py -o out.kl src.nka
```

For more options or features run `./numka.py -h`.

# Language Docs

NumKa is a C-style language so expect your classic curly brackets (`{}`), semicolons (`;`) and double slash (`//`) comments. When writing a new NumKa source file you can do two things, `import` or define a `fn`.

### Source Imports

NumKa has a very simple way of statically importing other source files not defined as source files to be compiled on the command line.

To import a source file `std.nka` simply pass in a import statement
```
import std.nka
```

The NumKa compiler will then search for that file in the current working directory and its include paths (defined using `-I` see `./numka.py -h` for more help)  and (if it didn't before) compile it to the output file. All definitions in the imported file will be implicitly available after the `import` statement.

### Basic Functions

To define a function in NumKa simply pass a `fn` followed by the function name.

```
fn my_func {
	
}
```

This `fn` and its body will be compiled into an equivalent karel-lang function with a name resembling `MY_FUNC` which will be visible in your catalogue.

> [!note]
> If you can't see your functions in your compiled output file, see [Implicit Usage](#implicit-usage) and check if your functions meet the requirements.

After you define a `fn` in your source, a `fn` can be called using their name with *or* without brackets `()` (brackets are later used for [Templates](#template-support))

```
fn triple_step {
	step;
	step;
	step;
}

fn my_func {
	// call triple_step - both ways are identical
	
	triple_step;
	triple_step();
}
```

#### Implicit Usage

NumKa supports multiple features (eg. [Templates](#template-support)) which makes compiling `fns` immediately on definition impossible. There for the `numka.py` compiler only compiles functions that are used somewhere else in the code base. However because NumKa doesn't have a concept of a `main` function, all functions would get ignored. 

To amend this NumKa defines a set of rules that if a `fn` followes these rules it considired *implicitly used* and will be compiled no matter if it is used by a different `fn` or not.

Currently for a `fn` to be considered as *implicitly used* the following must be met:
- no *template args* are used for the `fn` (but child [lambdas](#lambda-support) may include *templates args*)
- the `fn` doesn't include a `commit` keyword

> [!note]
> If a `fn` is marked as *implicitly used* its final name must be the original (upper-case) name of the `fn`. (eg. `MY_FUNC`) Otherwise if a `fn` is not marked as *implicitly used* and is only compiled to be used by other `fns` the final name is not specified and can differ from the `fn` name. (eg. `MY_FUNC<CL-NONE-...`)

### NumKa Keywords

An overview of available language keywords inside `fns`. 

#### Karel-lang built-ins

all built-in functions from karel-lang can be used by just calling them like you would expect (can be only called **without** brackets `()`)
```
fn my_func {
	// two steps and turn left
	
	step;
	step;
	
	left;
}
```

> [!note]
>As built-ins are reserved by karel-lang they cannot be used to define a new `fn`.

NumKa also implicitly defines two shorthands for `place` and `pick` as `++` and `--` respectively.

```
fn pick_three {
	--; --; --;
}
```

#### C keywords

some of NumKa keywords are derived from C notably `if`, `else`, `while` and `for`. While their syntax changed a bit their behaviour has not.

```
fn my_func {
	// if `is_flag` step once, else step twice
	if is_flag {
		step;
	} else {
		step; step;
	}
	
	// loop until `not_north` is not true (aka until is north)
	while not_north {
		left;
	}
	
	// loop 8 times
	for 8 {
		place;
	}
}
```

#### `recall` keyword

The `recall` keyword is a shorthand for doing a recursive call to the currently running `fn` or [lambda](#lambda-support). Again can be called with or without brackets.

```
// calls recursivelly until the current square is empty (of flags) 
fn recursive_clear {
	--;
	
	if is_flag {
		recall;
	}
}
```

#### `no_op` keyword

The `no_op` is a valid keyword which is ignored by the compiler and does not produce any karel-lang code to the output, it is mostly used in the context of [templates](#template-support) as they cannot contain empty values so a `no_op` is an alternative in some cases.

```
fn composite_fn(on_no_flag) {
	...
	
	if is_flag {
		--;
	} else {
		[on_no_flag];
	}

	...
}

fn my_func {
	// do not care about no_flag case
	composite_fn(no_op);
}
```

## Template Support

NumKa is built on a very limited platform in regards to runtime code flexibility. This causes problems when trying to reuse code as defined functions are fixed in place and cannot be modified to allow for reuse in other parts of the code base.

To fix this NumKa implements *compile-time* `fn` templates which allows the `fn` caller to modify the `fn` using its *template args*. *Template args* are essentially code-snippets which get pasted inside the `fn`.

To define a `fn` template, just pass n-number of *template args* into brackets following the `fn` name.

```
fn step_for(count) {
	for 5 {
		step;
	}
}
```

Currently the *template arg* `count` is not being used and will not affect the function, to insert the code-snippet from the caller, a *template target* in square brackets (`[]`) must be passed where the code-snippet should be inserted.

```
fn step_for(count) {
	for [count] {
		step;
	}
}
```

Now the number of steps made by the `step_for` function is defined by its *template arg*. To call `fn` templates simply call the `fn` with its name and its *template arg values* inside brackets (`()`)

```
fn step_for(count) {
	for [count] {
		step;
	}
}

fn my_func {
	// step 6 times, turn left and then step 2 more times
	
	step_for(6);
	
	left;
	step_for(2);
}
```

It is also fully supported and correct to have multiple levels of *template arg values* inside one another

```
fn move_kyte(move_impl) {
	if is_flag {
		--;
		recall;
		++;
	} else {
		[move_impl];
	}
}

fn do_stuff {
	
	...

	do_stuff(step_for(5));

	...

}
```

> [!note]
> Note that the `recall` keyword also counts as a `fn` call and so can include *template arg values* for the current `fn`. In the case that a recall keyword in a fn template doesn't have *template arg values* the current *values* from the current fn are used implicitly
> 
> ```
> fn my_func(v) {
> 	if [v] {
> 		recall([v]);
> 	}
> }
> ```

## Lambda support

Lambdas in NumKa are special unnamed functions defined inside of `fn` bodies. They are most of the time used as a code-segment which can `recall` itself, have its own *template args*, but also shares (inherits) parents `fn` *template args*. (and semi-share stack slices and `commit` behaviour, see [Stack Semantics](#stack-semantics)) 

Lambdas are defined inside of `fn` bodies and are called *in-place*.

To define a lambda pass a `{` to start the lambda, to define lambda *template args* pass the brackets before the `{`. Then after finishing the lambda close it using a `}` and another set of brackets, this time for *template arg values*.

```
fn my_func(v) {
	// define (and call) a basic lambda that recalls itself
	
	{
		--;
		if is_flag {
			recall;
		}
	};
	
	// define a template lambda
	
	(lv) {
		// inherits template arg from fn
		some_func([v]); 
		
		// uses its own template arg
		some_func([lv]); 
		
		// recalls lambda with a new template arg value
		recall([v]);
	} (52);
}
```

## Stack Semantics

> [!warning]
> Stack semantics and their compiler support is currently in it's early stages and is still considired **alpha** status. The support for the following is still very **WIP**

This section describes the NumKa language and compiler support for advanced call stack operations and "stack slices". With stack slices, numka allows to store limited stack-like memory and values inside karels function call stack with a variable like syntax.

A stack slice is a representation of a known part (a "slice") of the current call stack. (on the "stack") They can be created by calling (`push`ing) a [slice fn](#slice-fn) and capturing it as a stack slice. Then to "access" a slice you must `pop` it (destroying it in the process) which will return trough the call stack and trough the slice.

Due to the call stack based storage of stack slices, all slice lifetimes are relative to the current *scope*, that is that all slices can only exists and be accessed from the current `fn` or [lambda](#lambda-support) and cannot outlive it.

An example of where stack slices could be used is temporary storage for moving data around karels city
```
// define a slice fn that memorizes a value at the current position and writes it on a pop

fn store_value slicing {
	if is_flag {
		--;
		recall;
		++;
	} else {
		commit;
	}
}

// moves a value a step forward by using the store_value slice fn
fn move_value {
	val = push store_value;

	step;

	pop val;
}
```

> [!warning]
> Due to limitations of this method and the current compiler support, all slices can and must be accessed using a FILO (First In Last Out) order to preserve the call stack order.

> [!note]
> In the future some out-of-order stack operations (like `return push` which outlives a fn) may be supported but their usage and requirements would be strict and their support is not currenly planed 

#### Slice Fn

Slice `fn` is a `fn` which supports being a part of a [push](#push-keyword). A slice `fn` has additional requirements that **must** be followed by the user as these **cannot** be checked by the compiler. 

A slice `fn` is defined by including the `slicing` keyword after the `fn` name in its definition, by defining a `fn` as `slicing` you **guarantee** to the compiler that you as the user followed the following slice `fn` requirements:
- the `fn` or other `fns` or [lambdas](#lambda-support) contain a commit keyword
- when pushing, the `commit` keyword is invoked **exactly once** for the entire push

> [!warning]
> Failing to follow the slice `fn` requirements will not generate *any* compiler errors or warnings but *will* generate faulty karel-lang output.

An example of a simple slice fn:
```
// stores if a flag has been present when a slice has been pushed and adds a flag when the slice is poped 

fn store_flag slicing {
	if is_flag {
		commit;
		++;
	} else {
		commit;
	}
}
```

#### `push` keyword

A `push` is an abstraction of calling a slice `fn` to save a slice on the call stack. It can be used with the *slice assigment* syntax to create new stack slices.

Continuing the above example of `store_flag`:
```
...

// check for flag and move to the side to add the result

fn check_flag {
	slice = push store_flag;

	for 3 { step; }

	...
```

> [!note]
> Slice `push` operations count as a "normal" `fn` calls so templates can be used with the same syntax.

#### `pop` keyword

A `pop` is an abstraction of retuning trough a saved slice of the call stack. To `pop` a slice, just pass in a `pop` keyword with the slice variable you want to `pop`. All slices have to be `pop`ed in the opposite order they were `push`ed. (only the newest `push`ed slice can be `pop`ed)

Continuing the above example of `store_flag` and `check_flag`:
```
	...

	pop slice;
}
```

> [!note]
> All slices `push`ed on the stack must also be `pop`ed before the `fn` ending (no slices can be discarded)

#### `commit` keyword

The `commit` keyword is a part of a slice `fn` and shouldn't be used outside of `push` operations.

The `commit` keyword signals to the compiler that the stack slice in it's current form should be saved until it is `pop`ed. The compiler will then insert a call to the next *segment* of the `fn` that `push`ed the slice to continue execution.

> [!warning]
> Due to the implementation of stack slices, it is the *responsibility* of the *user* to invoke the `commit` keyword **exactly once** in a `push` operation. See [slice fns](#slice-fn) for more info.

> [!note]
> This keyword is supposed to be used inside [slice fns](#slice-fn). If `commit` is used outside of a slice `fn` a warning will be printed and the keyword ignored.