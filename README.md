# NumKa
a high-level language transpiled to karel-lang with support for lambdas, templates and stack semantics.

The NumKa compiler is currently in heavy *WIP*, expect bugs or missing features.

# Usage

To compile NumKa source files, clone this repo and use the `numka.py`
```sh
git clone https://github.com/Karel-industries/NumKa.git numka
cd numka
```

The `numka.py` compiler follows the gcc compiler flags where applicable so to compile source file `src.nka` to `out.kl` run
```sh
./numka.py -o out.kl src.nka
```

For more options or features see the run `./numka.py -h`.

# Language Docs

NumKa is a C-style language so expect your classic curly brackets (`{}`), semicolons (`;`) and double slash (`//`) comments. When writing a new NumKa source file you can do two things, `import` or define a `fn`.

### Source Imports

NumKa has a very simple way of statically importing other source files not defined as source files to be compiled on the command line.

To import a source file `std.nka` simply pass in a import statement
```
import std.nka
```

The NumKa compiler will then search for that file in the current working directory and its include paths (defined using `-I` see `./numka.py -h` for more help)  and (if it didn't before) compile it to the output file. All definitions in the imported file will be implicitly available.

### Basic Functions

To define a function in NumKa simply pass a `fn` followed by the function name.

```
fn my_func {
	
}
```

This `fn` and its body will be compiled into an equivalent karel-lang function with a name resembling `MY_FUNC<CL-NONE-TH[hash value]>` which will be visible in your catalogue.

> [!note]
> If you can't see your functions in your compiled output file, see Implicit Usage and check if your functions meet the requirements.

After you define a `fn` in your source, a `fn` can be called using their name with *or* without brackets `()` (brackets are later used for Templates)

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

The `recall` keyword is a shorthand for doing a recursive call to the currently running `fn` or lambda. Again can be called with or without brackets.

```
// calls recursivelly until the current square is empty (of flags) 
fn recursive_clear {
	--;
	
	if is_flag {
		recall;
	}
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

> [!note]
> Note that the `recall` keyword also counts as a `fn` call and so must include *template arg values* for the current `fn` (which *may or may not* be different from the current `fn` *template arg values*)
> 
> ```
> fn my_func(v) {
> 	if [v] {
> 		recall([v]);
> 	}
> }
> ```

## Lambda support

Lambdas in NumKa are special unnamed functions defined inside of `fn` bodies. They are most of the time used as a code-segment which can `recall` itself, have its own *template args*, but also shares (inherits) parents `fn` *template args*. (and semi-share stack slices and `commit` behaviour, see Stack Semantics) 

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
> Stack semantics and their compiler support has **not** been done yet. The following is purely informational and very **WIP**

NumKa keywords related to the advanced language support for call stack operations and "stack slices"

#### `commit` keyword

> [!note]
> This keyword is supposed to be used for stack `push` operations. If `commit` is used outside of a `push` a warning will be printed and the keyword ignored.

The `commit` keyword signals the compiler that at the point of the keyword is the exit point of the `push` and where the following *segment shim* of the caller should be called
