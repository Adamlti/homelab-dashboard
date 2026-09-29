import { useRef, useState } from 'react'
import { useProjectCollection } from '../hooks/useProjectCollection'
import { createPortal } from 'react-dom'
import { DndContext, DragOverlay, KeyboardSensor, PointerSensor, closestCenter, useSensor, useSensors } from '@dnd-kit/core'
import { SortableContext, arrayMove, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { Panel } from './Overview'
import { projectRequest } from '../projectApi'

const verticalOnly = ({ transform }) => ({ ...transform, x: 0 })

function ItemContent({ item }) {
  return <div className="roadmap-copy"><span className="tag">{item.phase}</span><h3>{item.title}</h3>{item.description && <p>{item.description}</p>}</div>
}

function SortableItem({ item, disabled, onEdit, onRemove }) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({
    id: item.id, disabled, transition: { duration: 220, easing: 'cubic-bezier(.2,.8,.2,1)' },
  })
  return <li ref={setNodeRef} data-roadmap-id={item.id} className={`roadmap-card ${isDragging ? 'drag-placeholder' : ''}`}
    style={{ transform: CSS.Transform.toString(transform), transition }}
    onPointerDown={event => {
      if (!event.target.closest('button, input, textarea, a')) listeners?.onPointerDown?.(event)
    }}>
    <button className="drag-handle" ref={setActivatorNodeRef} {...attributes} {...listeners} disabled={disabled} aria-label={`Move roadmap item: ${item.title}`} title="Drag to reorder. Keyboard: Space, arrow keys, Space.">⠿</button>
    <ItemContent item={item} />
    <div className="roadmap-actions"><button className="text-button" disabled={disabled} onClick={() => onEdit(item)} aria-label={`Edit roadmap item: ${item.title}`}>Edit</button><button className="text-button remove-button" disabled={disabled} onClick={() => onRemove(item)} aria-label={`Remove roadmap item: ${item.title}`}>Remove</button></div>
  </li>
}

export function Roadmap({ refreshToken }) {
  const { rows: items, setRows: setItems, loaded, busy, error, alive, load, save } = useProjectCollection('roadmap', refreshToken)
  const [form, setForm] = useState(null)
  const [activeId, setActiveId] = useState(null)
  const scroll = useRef(null)
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )
  function submit(event) {
    event.preventDefault()
    const { id, title, description, phase } = form
    save(async () => {
      const row = await projectRequest(id ? `roadmap/${id}` : 'roadmap', {
        method: id ? 'PATCH' : 'POST', body: JSON.stringify({ title, description, phase }),
      })
      if (!alive.current) return
      setItems(previous => id ? previous.map(item => item.id === id ? row : item) : [...previous, row])
      setForm(null)
      if (!id) requestAnimationFrame(() => scroll.current?.scrollTo({ top: scroll.current.scrollHeight, behavior: 'smooth' }))
    })
  }
  function remove(item) {
    if (!window.confirm(`Remove roadmap item “${item.title}”? This cannot be undone.`)) return
    save(async () => {
      await projectRequest(`roadmap/${item.id}`, { method: 'DELETE' })
      if (alive.current) setItems(previous => previous.filter(row => row.id !== item.id))
    })
  }
  function dropped({ active, over }) {
    setActiveId(null)
    if (!over || active.id === over.id) return
    const from = items.findIndex(item => item.id === active.id)
    const to = items.findIndex(item => item.id === over.id)
    if (from < 0 || to < 0) return
    const before = items
    const next = arrayMove(items, from, to)
    save(async () => {
      setItems(next)
      try {
        const saved = await projectRequest('roadmap/order', { method: 'PUT', body: JSON.stringify({ ids: next.map(item => item.id) }) })
        if (alive.current) setItems(saved)
      } catch (err) {
        if (alive.current) setItems(before)
        throw err
      }
    })
  }
  const activeItem = items.find(item => item.id === activeId)
  return <Panel className="project-panel roadmap-panel" title="Roadmap" subtitle="Plan the work · drag to reorder" aside={<div className="project-panel-actions"><span className="project-kind roadmap-kind">PLAN</span><button className="refresh" disabled={!loaded || busy || !!activeId} onClick={() => setForm({ title: '', description: '', phase: 'Next' })}>Add item</button></div>}>
    {error && <div className="notice" role="alert">{error} <button className="text-button" disabled={busy} onClick={load}>Refresh roadmap</button></div>}
    {form && <form className="roadmap-form" onSubmit={submit}>
      <label htmlFor="roadmap-title">Title<input id="roadmap-title" value={form.title} onChange={event => setForm({ ...form, title: event.target.value })} required maxLength={200} disabled={busy} autoFocus /></label>
      <label htmlFor="roadmap-phase">Phase<input id="roadmap-phase" value={form.phase} onChange={event => setForm({ ...form, phase: event.target.value })} required maxLength={40} disabled={busy} /></label>
      <label htmlFor="roadmap-description">Description<textarea id="roadmap-description" rows={2} value={form.description} onChange={event => setForm({ ...form, description: event.target.value })} maxLength={1000} disabled={busy} /></label>
      <div className="form-actions"><button className="refresh" disabled={busy || !form.title.trim() || !form.phase.trim()}>{form.id ? 'Save changes' : 'Add roadmap item'}</button><button type="button" className="text-button" disabled={busy} onClick={() => setForm(null)}>Cancel</button></div>
    </form>}
    {!loaded && !error && <p className="empty" role="status">Loading roadmap…</p>}
    <DndContext sensors={sensors} collisionDetection={closestCenter} modifiers={[verticalOnly]} onDragStart={({ active }) => setActiveId(active.id)} onDragCancel={() => setActiveId(null)} onDragEnd={dropped}>
      <SortableContext items={items.map(item => item.id)} strategy={verticalListSortingStrategy}>
        <ol className="roadmap-list project-scroll" ref={scroll} aria-label="Roadmap items">
          {items.map(item => <SortableItem key={item.id} item={item} disabled={busy || !!form} onEdit={setForm} onRemove={remove} />)}
        </ol>
      </SortableContext>
      {createPortal(<DragOverlay>{activeItem && <div className="roadmap-card drag-overlay"><span className="drag-handle">⠿</span><ItemContent item={activeItem} /></div>}</DragOverlay>, document.body)}
    </DndContext>
    {loaded && !items.length && <p className="empty">Your roadmap is empty. Add an item to get started.</p>}
    <p className="panel-footnote" role="status">{busy ? 'Saving roadmap…' : `${items.length} items · Order saved on adamserv`}</p>
  </Panel>
}
