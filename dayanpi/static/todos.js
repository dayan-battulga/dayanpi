// The To-do card: the running list, which item is current, and the time each one has collected.
// The list arrives with every stats snapshot (app.js re-broadcasts them as "dayanpi:snapshot");
// a change goes to /api/todos, and its reply redraws the list right away.

const ICON_PICK =
  '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><circle cx="12" cy="12" r="8"></circle><circle cx="12" cy="12" r="3" fill="currentColor"></circle></svg>';
const ICON_DELETE =
  '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"></path></svg>';

const todoEls = {
  count: document.getElementById("todo-count"),
  form: document.getElementById("todo-form"),
  input: document.getElementById("todo-input"),
  open: document.getElementById("todo-open"),
  doneTitle: document.getElementById("todo-done-title"),
  done: document.getElementById("todo-done"),
};

let todoSignature = "";
let todoTimes = new Map(); // item id -> its time element, so the clock can tick without a redraw
let editingId = null;

async function sendTodo(method, path, body) {
  try {
    const response = await fetch(path, {
      method,
      headers: { "Content-Type": "application/json" },
      body: body == null ? undefined : JSON.stringify(body),
    });
    if (response.ok) {
      renderTodos((await response.json()).todos);
    }
  } catch (error) {
    // The next snapshot shows the real list either way.
  }
}

function createIconButton(className, label, icon) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `todo-icon ${className}`;
  button.setAttribute("aria-label", label);
  button.innerHTML = icon;
  return button;
}

function startEditing(item, textButton) {
  editingId = item.id;
  const input = document.createElement("input");
  input.className = "todo-input";
  input.value = item.text;
  input.maxLength = 200;
  input.setAttribute("aria-label", `Edit: ${item.text}`);
  let finished = false;
  const finish = (save) => {
    if (!finished) {
      finished = true;
      editingId = null;
      todoSignature = ""; // the next snapshot redraws, even if the save fails
      const text = input.value.trim();
      if (save && text !== "" && text !== item.text) {
        textButton.textContent = text;
        sendTodo("PATCH", `/api/todos/${item.id}`, { text });
      }
      input.replaceWith(textButton);
    }
  };
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      finish(true);
    } else if (event.key === "Escape") {
      finish(false);
    }
  });
  input.addEventListener("blur", () => finish(true));
  textButton.replaceWith(input);
  input.focus();
  input.select();
}

function buildTodoRow(item, done, current) {
  const row = document.createElement("li");
  row.className = "todo-item";
  row.classList.toggle("is-current", current);
  row.classList.toggle("is-done", done);

  const check = document.createElement("input");
  check.type = "checkbox";
  check.className = "todo-check";
  check.checked = done;
  check.setAttribute("aria-label", `${done ? "Not done" : "Done"}: ${item.text}`);
  check.addEventListener("change", () => sendTodo("PATCH", `/api/todos/${item.id}`, { done: check.checked }));

  const text = document.createElement("button");
  text.type = "button";
  text.className = "todo-text";
  text.textContent = item.text;
  text.title = "Edit";
  text.addEventListener("click", () => startEditing(item, text));

  const time = document.createElement("span");
  time.className = "todo-time mono";
  todoTimes.set(item.id, time);
  row.append(check, text, time);

  if (!done) {
    const pick = createIconButton("todo-pick", current ? `Stop working on: ${item.text}` : `Work on: ${item.text}`, ICON_PICK);
    pick.setAttribute("aria-pressed", String(current));
    pick.title = current ? "Current: collecting time while you work in a block" : "Make current";
    pick.addEventListener("click", () => sendTodo("PATCH", `/api/todos/${item.id}`, { current: !current }));
    row.append(pick);
  }
  const remove = createIconButton("todo-delete", `Delete: ${item.text}`, ICON_DELETE);
  remove.addEventListener("click", () => sendTodo("DELETE", `/api/todos/${item.id}`));
  row.append(remove);
  return row;
}

// Every snapshot calls this, so it only rebuilds the rows when an item changed, and never mid-edit.
function renderTodos(todos) {
  const shape = (items) => items.map((item) => [item.id, item.text]);
  const signature = JSON.stringify([todos.current, shape(todos.open), shape(todos.done)]);
  if (signature !== todoSignature && editingId == null) {
    todoSignature = signature;
    todoTimes = new Map();
    const openRows = todos.open.map((item) => buildTodoRow(item, false, item.id === todos.current));
    if (openRows.length === 0) {
      const empty = document.createElement("li");
      empty.className = "todo-empty";
      empty.textContent = todos.done.length > 0 ? "All done. Nice." : "Nothing to do yet.";
      openRows.push(empty);
    }
    todoEls.open.replaceChildren(...openRows);
    todoEls.done.replaceChildren(...todos.done.map((item) => buildTodoRow(item, true, false)));
    todoEls.doneTitle.hidden = todos.done.length === 0;
    todoEls.count.textContent = todos.open.length > 0 ? `${todos.open.length} open` : "";
  }
  for (const item of [...todos.open, ...todos.done]) {
    const time = todoTimes.get(item.id);
    if (time != null) {
      time.textContent = item.seconds > 0 ? formatDuration(item.seconds) : "—";
    }
  }
}

todoEls.form.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = todoEls.input.value.trim();
  if (text !== "") {
    todoEls.input.value = "";
    sendTodo("POST", "/api/todos", { text });
  }
});

window.addEventListener("dayanpi:snapshot", (event) => {
  const todos = event.detail?.focus?.todos;
  if (todos != null) {
    renderTodos(todos);
  }
});
