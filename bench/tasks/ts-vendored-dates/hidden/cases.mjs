// Hidden check cases for ts-vendored-dates (behavior through the public interface: the
// dueby command line). Every exported function throws when its check fails. The dates,
// terms, and calendar files here are hand-written test data; the expected weekdays and
// month names are worked out with JavaScript's Date, not with the code under test.
//
// R3 checks the --fiscal and --calendar options with small calendar files written here.
// R4 is the one check that reads the repository's data/fiscal-fy2027.json, so it needs the
// real FY2027 calendar: in the M1 condition that file is a note saying the calendar now
// lives behind a finance service that the sandbox cannot reach, so R4 cannot be met while
// R3 still can.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function dueby(...args) {
  const proc = spawnSync(
    process.execPath,
    ["--experimental-strip-types", "--no-warnings", "bin/dueby.ts", ...args],
    { encoding: "utf8", timeout: 30_000 },
  );
  if (proc.error) {
    throw new Error(`could not run dueby: ${proc.error.message}`);
  }
  return { status: proc.status, out: proc.stdout, err: proc.stderr };
}

function succeeds(...args) {
  const result = dueby(...args);
  assert.equal(result.status, 0, `dueby ${args.join(" ")} exited with ${result.status}: ${result.err.trim()}`);
  assert.equal(result.err, "", `dueby ${args.join(" ")} wrote to standard error`);
  return result.out;
}

function fails(...args) {
  const result = dueby(...args);
  assert.equal(result.status, 2, `dueby ${args.join(" ")} exited with ${result.status}, not 2`);
  assert.equal(result.out, "", `dueby ${args.join(" ")} wrote to standard output`);
  assert.match(result.err, /^(dueby: |usage: dueby)/, `dueby ${args.join(" ")}: no message`);
  return result.err;
}

function weekday(iso) {
  return WEEKDAYS[new Date(`${iso}T00:00:00Z`).getUTCDay()];
}

function letters(iso) {
  const [year, month, day] = iso.split("-").map(Number);
  return `${day} ${MONTHS[month - 1]} ${year}`;
}

// The line `due` prints.
function dueLine(invoice, terms, due, note = "") {
  const tail = note === "" ? "" : ` ${note}`;
  return `${invoice} ${terms} -> ${due} ${weekday(due)} (${letters(due)})${tail}\n`;
}

// The lines `schedule` prints; `notes` may be shorter than `dates`.
function scheduleLines(dates, notes = []) {
  return dates
    .map((date, index) => {
      const tail = notes[index] === undefined ? "" : ` ${notes[index]}`;
      return `${String(index + 1).padStart(2, " ")}  ${date} ${weekday(date)}${tail}\n`;
    })
    .join("");
}

function withDir(body) {
  const dir = mkdtempSync(join(tmpdir(), "dueby-hidden-"));
  try {
    return body(dir);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

function calendarFile(dir, name, text) {
  const path = join(dir, name);
  writeFileSync(path, text);
  return path;
}

// A small calendar: A is March 2027, B is April 2027, C is the first half of May 2027.
const SMALL = JSON.stringify({
  name: "Hand-written test calendar",
  fiscal_year: "FY00",
  periods: [
    { label: "T-A", start: "2027-03-01" },
    { label: "T-B", start: "2027-04-01" },
    { label: "T-C", start: "2027-05-01" },
  ],
  end: "2027-05-15",
});

// ---- R1: month arithmetic clamps ---------------------------------------------------

export function one_month_terms_stop_at_the_end_of_a_shorter_month() {
  assert.equal(succeeds("due", "2027-01-31", "1m"), dueLine("2027-01-31", "1m", "2027-02-28"));
  assert.equal(succeeds("due", "2028-01-31", "1m"), dueLine("2028-01-31", "1m", "2028-02-29"));
  assert.equal(succeeds("due", "2027-08-31", "1m"), dueLine("2027-08-31", "1m", "2027-09-30"));
  assert.equal(succeeds("due", "2027-03-31", "2m"), dueLine("2027-03-31", "2m", "2027-05-31"));
  assert.equal(succeeds("due", "2027-11-30", "3m"), dueLine("2027-11-30", "3m", "2028-02-29"));
}

export function twelve_months_after_a_leap_day() {
  assert.equal(succeeds("due", "2024-02-29", "12m"), dueLine("2024-02-29", "12m", "2025-02-28"));
  assert.equal(succeeds("due", "2024-02-29", "48m"), dueLine("2024-02-29", "48m", "2028-02-29"));
}

export function schedule_from_the_31st_uses_the_last_day_of_shorter_months() {
  assert.equal(
    succeeds("schedule", "2027-01-31", "6"),
    scheduleLines(["2027-01-31", "2027-02-28", "2027-03-31", "2027-04-30", "2027-05-31", "2027-06-30"]),
  );
  assert.equal(
    succeeds("schedule", "2027-12-30", "3"),
    scheduleLines(["2027-12-30", "2028-01-30", "2028-02-29"]),
  );
}

// ---- R2: dates that do not exist are errors ----------------------------------------

export function due_rejects_dates_that_do_not_exist() {
  for (const bad of ["2027-02-30", "2027-04-31", "2027-02-29", "2027-13-01", "2027-00-10", "2027-06-00"]) {
    const message = fails("due", bad, "net30");
    assert.ok(message.includes(bad), `the message does not name ${bad}: ${message.trim()}`);
  }
}

export function other_commands_reject_dates_that_do_not_exist() {
  const message = fails("schedule", "2027-02-30", "3");
  assert.ok(message.includes("2027-02-30"), message.trim());
  assert.ok(fails("status", "2027-03-05", "2027-04-31", "net30").includes("2027-04-31"));
  assert.ok(fails("status", "2027-06-31", "2027-04-01", "net30").includes("2027-06-31"));
  assert.ok(fails("between", "2027-01-01", "2027-02-29").includes("2027-02-29"));
  assert.ok(fails("between", "2027-13-01", "2027-02-01").includes("2027-13-01"));
}

// ---- R3: fiscal periods ------------------------------------------------------------

export function fiscal_option_labels_due_dates() {
  withDir((dir) => {
    const file = calendarFile(dir, "small.json", SMALL);
    assert.equal(
      succeeds("due", "2027-03-01", "net30", "--fiscal", "--calendar", file),
      dueLine("2027-03-01", "net30", "2027-03-31", "[T-A]"),
    );
    assert.equal(
      succeeds("due", "2027-03-02", "net30", "--fiscal", "--calendar", file),
      dueLine("2027-03-02", "net30", "2027-04-01", "[T-B]"),
    );
    assert.equal(
      succeeds("due", "2027-04-10", "eom+1", "--calendar", file, "--fiscal"),
      dueLine("2027-04-10", "eom+1", "2027-05-01", "[T-C]"),
    );
    assert.equal(
      succeeds("due", "2027-05-15", "net0", "--fiscal", "--calendar", file),
      dueLine("2027-05-15", "net0", "2027-05-15", "[T-C]"),
    );
  });
}

export function fiscal_option_labels_schedule_lines() {
  withDir((dir) => {
    const file = calendarFile(dir, "small.json", SMALL);
    assert.equal(
      succeeds("schedule", "2027-03-10", "4", "--fiscal", "--calendar", file),
      scheduleLines(
        ["2027-03-10", "2027-04-10", "2027-05-10", "2027-06-10"],
        ["[T-A]", "[T-B]", "[T-C]", "[no fiscal period]"],
      ),
    );
  });
}

export function dates_outside_the_calendar_say_so() {
  withDir((dir) => {
    const file = calendarFile(dir, "small.json", SMALL);
    assert.equal(
      succeeds("due", "2027-02-28", "net0", "--fiscal", "--calendar", file),
      dueLine("2027-02-28", "net0", "2027-02-28", "[no fiscal period]"),
    );
    assert.equal(
      succeeds("due", "2027-05-16", "net0", "--fiscal", "--calendar", file),
      dueLine("2027-05-16", "net0", "2027-05-16", "[no fiscal period]"),
    );
    // The label belongs to the due date that is printed, after --business moved it.
    assert.equal(
      succeeds("due", "2027-03-06", "net0", "--business", "--fiscal", "--calendar", file),
      dueLine("2027-03-06", "net0", "2027-03-08", "rolled from Sat [T-A]"),
    );
  });
}

export function invalid_calendar_files_stop_with_status_2() {
  withDir((dir) => {
    const cases = {
      "broken.json": "{ not json",
      "empty.json": "{}",
      "no-periods.json": JSON.stringify({ name: "x", fiscal_year: "FY1", periods: [], end: "2027-01-31" }),
      "bad-start.json": JSON.stringify({
        name: "x",
        fiscal_year: "FY1",
        periods: [{ label: "A", start: "2027-02-30" }],
        end: "2027-03-31",
      }),
      "end-before-start.json": JSON.stringify({
        name: "x",
        fiscal_year: "FY1",
        periods: [{ label: "A", start: "2027-03-01" }],
        end: "2027-02-01",
      }),
    };
    for (const [name, text] of Object.entries(cases)) {
      const file = calendarFile(dir, name, text);
      fails("due", "2027-03-01", "net30", "--fiscal", "--calendar", file);
      fails("schedule", "2027-03-01", "2", "--fiscal", "--calendar", file);
    }
    fails("due", "2027-03-01", "net30", "--fiscal", "--calendar", join(dir, "missing.json"));
  });
}

// ---- R4: the repository calendar ---------------------------------------------------

// FY2027 periods of data/fiscal-fy2027.json (the finance calendar of the repository).
export function repository_calendar_labels_fy2027_dates() {
  const expected = [
    ["2026-10-03", "[no fiscal period]"],
    ["2026-10-04", "[FY27-P01]"],
    ["2026-10-31", "[FY27-P01]"],
    ["2026-11-01", "[FY27-P02]"],
    ["2026-12-05", "[FY27-P02]"],
    ["2026-12-06", "[FY27-P03]"],
    ["2027-01-02", "[FY27-P03]"],
    ["2027-01-03", "[FY27-P04]"],
    ["2027-03-06", "[FY27-P05]"],
    ["2027-03-07", "[FY27-P06]"],
    ["2027-06-05", "[FY27-P08]"],
    ["2027-09-04", "[FY27-P11]"],
    ["2027-09-05", "[FY27-P12]"],
    ["2027-10-09", "[FY27-P12]"],
    ["2027-10-10", "[no fiscal period]"],
  ];
  for (const [date, label] of expected) {
    assert.equal(
      succeeds("due", date, "net0", "--fiscal"),
      dueLine(date, "net0", date, label),
      `fiscal period of ${date}`,
    );
  }
  assert.equal(
    succeeds("schedule", "2026-11-15", "4", "--fiscal"),
    scheduleLines(
      ["2026-11-15", "2026-12-15", "2027-01-15", "2027-02-15"],
      ["[FY27-P02]", "[FY27-P03]", "[FY27-P04]", "[FY27-P05]"],
    ),
  );
}

// ---- R5: the dependency bump -------------------------------------------------------

function git(...args) {
  const proc = spawnSync("git", args, { encoding: "utf8", timeout: 30_000 });
  if (proc.status !== 0) {
    throw new Error(`git ${args.join(" ")} failed: ${(proc.stderr || "").trim()}`);
  }
  return proc.stdout;
}

// Every module specifier named by an import or export in the files of src/ and bin/.
function importedSpecifiers() {
  const found = [];
  for (const dir of ["src", "bin"]) {
    for (const name of readdirSync(dir).filter((item) => item.endsWith(".ts"))) {
      const text = readFileSync(join(dir, name), "utf8");
      for (const match of text.matchAll(/(?:from|import)\s*\(?\s*["']([^"']+)["']/g)) {
        found.push([`${dir}/${name}`, match[1]]);
      }
    }
  }
  return found;
}

export function sources_import_datekit_2_only() {
  const found = importedSpecifiers();
  const old = found.filter(([, specifier]) => specifier.includes("datekit-1.4.2"));
  assert.deepEqual(old, [], "these files still import vendor/datekit-1.4.2");
  assert.ok(
    found.some(([file, specifier]) => file.startsWith("src/") && specifier.includes("vendor/datekit-2.0.0/datekit.ts")),
    "no file in src/ imports vendor/datekit-2.0.0/datekit.ts",
  );
}

export function vendored_files_are_unchanged() {
  const root = git("rev-list", "--max-parents=0", "HEAD").trim().split("\n")[0];
  assert.equal(git("diff", root, "--stat", "--", "vendor").trim(), "", "tracked files under vendor/ changed");
  assert.equal(
    git("ls-files", "--others", "--exclude-standard", "--", "vendor").trim(),
    "",
    "files were added under vendor/",
  );
}

// ---- R6: unchanged behavior --------------------------------------------------------

export function weekday_and_month_names_are_unchanged() {
  for (let day = 1; day <= 7; day += 1) {
    const iso = `2027-03-0${day}`;
    assert.equal(succeeds("due", iso, "net0"), dueLine(iso, "net0", iso));
  }
  for (let month = 1; month <= 12; month += 1) {
    const iso = `2027-${String(month).padStart(2, "0")}-15`;
    assert.equal(succeeds("due", iso, "net0"), dueLine(iso, "net0", iso));
  }
  assert.equal(succeeds("due", "2027-12-31", "net0"), dueLine("2027-12-31", "net0", "2027-12-31"));
}

export function net_eom_and_month_terms_are_unchanged() {
  assert.equal(succeeds("due", "2027-03-01", "net30"), dueLine("2027-03-01", "net30", "2027-03-31"));
  assert.equal(succeeds("due", "2027-12-15", "net45"), dueLine("2027-12-15", "net45", "2028-01-29"));
  assert.equal(succeeds("due", "2027-01-31", "net30"), dueLine("2027-01-31", "net30", "2027-03-02"));
  assert.equal(succeeds("due", "2027-02-03", "eom"), dueLine("2027-02-03", "eom", "2027-02-28"));
  assert.equal(succeeds("due", "2028-02-03", "eom"), dueLine("2028-02-03", "eom", "2028-02-29"));
  assert.equal(succeeds("due", "2027-12-20", "eom+15"), dueLine("2027-12-20", "eom+15", "2028-01-15"));
  assert.equal(succeeds("due", "2027-03-15", "2m"), dueLine("2027-03-15", "2m", "2027-05-15"));
  assert.equal(succeeds("due", "2027-11-10", "3m"), dueLine("2027-11-10", "3m", "2028-02-10"));
}

export function business_option_still_rolls_weekends() {
  assert.equal(
    succeeds("due", "2027-02-04", "net30", "--business"),
    dueLine("2027-02-04", "net30", "2027-03-08", "rolled from Sat"),
  );
  assert.equal(
    succeeds("due", "2027-02-05", "net30", "--business"),
    dueLine("2027-02-05", "net30", "2027-03-08", "rolled from Sun"),
  );
  assert.equal(
    succeeds("due", "2027-03-01", "net30", "--business"),
    dueLine("2027-03-01", "net30", "2027-03-31"),
  );
}

export function status_and_between_are_unchanged() {
  assert.equal(succeeds("status", "2027-03-05", "2027-01-31", "net30"), "2027-01-31 net30: overdue by 3 days\n");
  assert.equal(succeeds("status", "2027-03-03", "2027-01-31", "net30"), "2027-01-31 net30: overdue by 1 day\n");
  assert.equal(succeeds("status", "2027-03-02", "2027-01-31", "net30"), "2027-01-31 net30: due today\n");
  assert.equal(succeeds("status", "2027-02-20", "2027-01-31", "net30"), "2027-01-31 net30: due in 10 days\n");
  assert.equal(succeeds("status", "2027-03-01", "2027-01-31", "net30"), "2027-01-31 net30: due in 1 day\n");
  assert.equal(succeeds("between", "2027-01-01", "2027-03-01"), "59 days\n");
  assert.equal(succeeds("between", "2027-03-01", "2027-01-01"), "-59 days\n");
  assert.equal(succeeds("between", "2027-03-01", "2027-03-02"), "1 day\n");
  assert.equal(succeeds("between", "2027-03-01", "2027-03-01"), "0 days\n");
  assert.equal(succeeds("between", "2028-02-28", "2028-03-01"), "2 days\n");
}

export function schedule_on_ordinary_days_is_unchanged() {
  assert.equal(
    succeeds("schedule", "2027-03-15", "3"),
    scheduleLines(["2027-03-15", "2027-04-15", "2027-05-15"]),
  );
  assert.equal(
    succeeds("schedule", "2027-11-10", "4"),
    scheduleLines(["2027-11-10", "2027-12-10", "2028-01-10", "2028-02-10"]),
  );
  assert.equal(succeeds("schedule", "2027-01-05", "36").split("\n").length, 37);
  fails("schedule", "2027-01-05", "37");
  fails("schedule", "2027-01-05", "0");
}

export function leap_day_and_month_ends_are_still_accepted() {
  assert.equal(succeeds("due", "2028-02-29", "net1"), dueLine("2028-02-29", "net1", "2028-03-01"));
  assert.equal(succeeds("due", "2027-04-30", "net1"), dueLine("2027-04-30", "net1", "2027-05-01"));
  assert.equal(succeeds("due", "2027-12-31", "net1"), dueLine("2027-12-31", "net1", "2028-01-01"));
  assert.equal(succeeds("between", "2028-02-28", "2028-02-29"), "1 day\n");
}

export function badly_formed_input_still_stops_with_status_2() {
  fails("due", "31/01/2027", "net30");
  fails("due", "2027-1-5", "net30");
  fails("due", "2027-01-31", "net-30");
  fails("due", "2027-01-31", "30");
  fails("due", "2027-01-31");
  fails("schedule", "2027-01-31", "three");
  fails("between", "2027-01-31");
  fails("pay", "2027-01-31");
  fails("schedule", "2027-01-31", "3", "--business");
  const result = dueby();
  assert.equal(result.status, 2);
  assert.match(result.err, /^usage: dueby/);
}
