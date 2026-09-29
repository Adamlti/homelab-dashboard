import { useEffect, useRef, useState } from 'react'
import { useProjectCollection } from '../hooks/useProjectCollection'
import { Panel } from './Overview'

import { Roadmap } from './Roadmap'
import { projectRequest } from '../projectApi'

const taskRequest = (path = '', options) => projectRequest(`tasks${path}`, options)

export function Project({ refreshToken }) {
  const { rows: tasks, setRows: setTasks, loaded, busy, error, alive: active, load, save } = useProjectCollection('tasks', refreshToken)
  const [title, setTitle] = useState('')
  const [editing, setEditing] = useState(null)
  const [notes, setNotes] = useState({ content: '', updated_at: null })
  const [notesLoaded, setNotesLoaded] = useState(false)
  const [notesBusy, setNotesBusy] = useState(false)
  const [notesError, setNotesError] = useState(null)
  const notesAlive = useRef(false)
  useEffect(() => {
    notesAlive.current = true
    let cancelled = false
    projectRequest('notes').then(value => {
      if (!cancelled && notesAlive.current) { setNotes(value); setNotesLoaded(true); setNotesError(null) }
    }).catch(error => {
      if (!cancelled && notesAlive.current) { setNotesLoaded(true); setNotesError(error.message) }
    })
    return () => { cancelled = true; notesAlive.current = false }
  }, [refreshToken])
  async function saveNotes(event) {
    event.preventDefault()
    setNotesBusy(true); setNotesError(null)
    try {
      const saved = await projectRequest('notes', { method: 'PATCH', body: JSON.stringify({ content: notes.content }) })
      if (notesAlive.current) setNotes(saved)
    } catch (error) {
      if (notesAlive.current) setNotesError(error.message)
    } finally {
      if (notesAlive.current) setNotesBusy(false)
    }
  }
  function edit(event) {
    event.preventDefault()
    save(async () => {
      const updated = await taskRequest(`/${editing.id}`, { method: 'PATCH', body: JSON.stringify({ title: editing.title.trim() }) })
      if (active.current) { setTasks(previous => previous.map(item => item.id === updated.id ? updated : item)); setEditing(null) }
    })
  }
  function add(event) {
    event.preventDefault()
    if (!title.trim()) return
    save(async () => {
      const task = await taskRequest('', { method: 'POST', body: JSON.stringify({ title: title.trim() }) })
      if (active.current) { setTasks(previous => [...previous, task]); setTitle('') }
    })
  }
  function toggle(task) {
    save(async () => {
      const updated = await taskRequest(`/${task.id}`, { method: 'PATCH', body: JSON.stringify({ completed: !task.completed }) })
      if (active.current) setTasks(previous => previous.map(item => item.id === updated.id ? updated : item))
    })
  }
  function remove(task) {
    if (!window.confirm(`Remove task “${task.title}”? This cannot be undone.`)) return
    save(async () => {
      await taskRequest(`/${task.id}`, { method: 'DELETE' })
      if (active.current) setTasks(previous => previous.filter(item => item.id !== task.id))
    })
  }
  return <div className="project-workspace">
    <div className="project-columns">
    <Roadmap refreshToken={refreshToken} />
    <Panel className="project-panel todo-panel" title="To-do list" subtitle="Small actions · check them off" aside={<span className="project-kind todo-kind">ACTION</span>}>
      {error && <div className="notice" role="alert">{error} <button onClick={load} disabled={busy}>Retry</button></div>}
      <form className="task-form" onSubmit={add}>
        <label htmlFor="new-task">New task</label>
        <div><input id="new-task" value={title} onChange={event => setTitle(event.target.value)} maxLength={200} placeholder="What needs doing?" required disabled={busy || !loaded} /><button className="refresh" type="submit" disabled={busy || !loaded || !title.trim()}>Add task</button></div>
      </form>
      {editing && <form className="roadmap-form" onSubmit={edit}>
        <label htmlFor="edit-task-title">Task title<input id="edit-task-title" value={editing.title} onChange={event => setEditing({ ...editing, title: event.target.value })} maxLength={200} required disabled={busy} autoFocus /></label>
        <div className="form-actions"><button className="refresh" disabled={busy || !editing.title.trim()}>Save task</button><button type="button" className="text-button" disabled={busy} onClick={() => setEditing(null)}>Cancel</button></div>
      </form>}
      {!loaded && !error && <p className="empty" role="status">Loading tasks…</p>}
      <ul className="task-list project-scroll">{tasks.map(task => <li key={task.id}><label className={task.completed ? 'task-done' : ''}><input type="checkbox" checked={task.completed} disabled={busy} onChange={() => toggle(task)} />{task.title}</label><div className="task-actions"><button className="text-button" aria-label={`Edit task: ${task.title}`} disabled={busy || !!editing} onClick={() => setEditing(task)}>Edit</button><button className="text-button remove-button" aria-label={`Remove task: ${task.title}`} disabled={busy || !!editing} onClick={() => remove(task)}>Remove</button></div></li>)}</ul>
      {loaded && !tasks.length && <p className="empty">No tasks yet. Add your first task above.</p>}
      <p className="panel-footnote" role="status">{busy ? 'Saving…' : `${tasks.filter(task => task.completed).length} of ${tasks.length} completed`}</p>
    </Panel>
    </div>
    <Panel className="project-panel notes-panel" title="Notes to self" subtitle="A persistent scratchpad saved on adamserv" aside={<span className="project-kind notes-kind">SCRATCHPAD</span>}>
      {notesError && <div className="notice" role="alert">{notesError}</div>}
      {!notesLoaded ? <p className="empty" role="status">Loading notes…</p> : <form className="notes-form" onSubmit={saveNotes}>
        <label htmlFor="notes-to-self">Notes to self<textarea id="notes-to-self" value={notes.content} onChange={event => setNotes(previous => ({ ...previous, content: event.target.value }))} maxLength={5000} rows={6} placeholder="Capture ideas, reminders, commands, or context for later…" disabled={notesBusy} /></label>
        <div className="notes-footer"><span className="panel-footnote">{notes.content.length}/5000 characters{notes.updated_at && ` · Saved ${new Date(notes.updated_at).toLocaleString()}`}</span><button className="refresh" disabled={notesBusy}>{notesBusy ? 'Saving…' : 'Save notes'}</button></div>
      </form>}
    </Panel>
  </div>
}
