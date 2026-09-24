/* Face Attendance - dashboard (vanilla JS, no build step). */
(function () {
	'use strict'

	const APP = 'faceattendance'
	const T = (s, v) => t(APP, s, v)
	const API = OC.linkToOCS('apps/' + APP + '/api/v1', 2)
	const DAY = 86400

	const state = {
		tab: 'summary',
		date: todayStr(),
		room: '',
		search: '',
		workStart: load('workStart', '09:00'),
		events: [],
		roster: [],
		timer: null,
	}

	// ---------------------------------------------------------------- utils
	function load(key, def) {
		try { return localStorage.getItem(APP + '.' + key) || def } catch (e) { return def }
	}
	function save(key, value) {
		try { localStorage.setItem(APP + '.' + key, value) } catch (e) { /* private mode */ }
	}
	function pad(n) { return String(n).padStart(2, '0') }
	function todayStr() {
		const d = new Date()
		return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate())
	}
	function dayBounds(dateStr) {
		const [y, m, d] = dateStr.split('-').map(Number)
		const from = Math.floor(new Date(y, m - 1, d).getTime() / 1000)
		return [from, from + DAY]
	}
	function hhmm(ts) {
		const d = new Date(ts * 1000)
		return pad(d.getHours()) + ':' + pad(d.getMinutes())
	}
	function hhmmss(ts) {
		return hhmm(ts) + ':' + pad(new Date(ts * 1000).getSeconds())
	}
	function minutesOf(hm) {
		const [h, m] = hm.split(':').map(Number)
		return h * 60 + m
	}
	function el(tag, attrs, ...children) {
		const node = document.createElement(tag)
		for (const [k, v] of Object.entries(attrs || {})) {
			if (k === 'class') node.className = v
			else if (k.startsWith('on')) node.addEventListener(k.slice(2), v)
			else if (v !== null && v !== undefined && v !== false) node.setAttribute(k, v === true ? '' : v)
		}
		for (const c of children.flat()) {
			if (c === null || c === undefined || c === false) continue
			node.append(c instanceof Node ? c : document.createTextNode(String(c)))
		}
		return node
	}
	function snapUrl(id) { return OC.generateUrl('/apps/' + APP + '/snapshot/' + id) }
	function thumb(ev) {
		if (!ev || !ev.hasSnapshot) return el('div', { class: 'fa-thumb fa-thumb--empty' })
		return el('a', { href: snapUrl(ev.id), target: '_blank', rel: 'noopener' },
			el('img', { class: 'fa-thumb', src: snapUrl(ev.id), loading: 'lazy', alt: '' }))
	}

	async function fetchEvents(from, to, extra) {
		const params = new URLSearchParams({ format: 'json', from, to, ...(extra || {}) })
		const res = await fetch(API + 'events?' + params, {
			headers: { 'OCS-APIRequest': 'true', requesttoken: OC.requestToken, Accept: 'application/json' },
		})
		if (!res.ok) throw new Error('HTTP ' + res.status)
		return (await res.json()).ocs.data
	}

	// ---------------------------------------------------------------- data
	async function refresh() {
		const [from, to] = dayBounds(state.date)
		const status = document.getElementById('fa-status')
		try {
			status.textContent = T('Loading…')
			const [events, recent] = await Promise.all([
				fetchEvents(from, to, { limit: 10000 }),
				// people seen in the 30 days before - used to list who is absent
				fetchEvents(from - 30 * DAY, from, { limit: 10000 }),
			])
			state.events = events
			state.roster = [...new Set(recent.concat(events).map(e => e.person).filter(Boolean))].sort((a, b) => a.localeCompare(b))
			status.textContent = T('Updated {time}', { time: hhmmss(Date.now() / 1000) })
		} catch (e) {
			status.textContent = T('Could not load data: {error}', { error: e.message })
		}
		render()
	}

	function filtered() {
		const q = state.search.trim().toLowerCase()
		return state.events.filter(e =>
			(!state.room || e.room === state.room)
			&& (!q || (e.person || T('Unknown')).toLowerCase().includes(q)))
	}

	function summarize(events) {
		const by = new Map()
		for (const e of events) {
			if (!e.person) continue
			let s = by.get(e.person)
			if (!s) {
				s = { person: e.person, first: e, last: e, rooms: new Set(), count: 0 }
				by.set(e.person, s)
			}
			if (e.ts < s.first.ts) s.first = e
			if (e.ts > s.last.ts) s.last = e
			s.rooms.add(e.room)
			s.count++
		}
		return [...by.values()].sort((a, b) => a.first.ts - b.first.ts)
	}

	// ---------------------------------------------------------------- views
	function renderSummary(events) {
		const rows = summarize(events)
		const startMin = minutesOf(state.workStart)
		const present = new Set(rows.map(r => r.person))
		const absent = state.roster.filter(p => !present.has(p)
			&& (!state.search || p.toLowerCase().includes(state.search.toLowerCase())))
		const late = rows.filter(r => {
			const d = new Date(r.first.ts * 1000)
			return d.getHours() * 60 + d.getMinutes() > startMin
		}).length

		const cards = el('div', { class: 'fa-cards' },
			card(T('Present'), rows.length),
			card(T('Late'), late, late ? 'warn' : ''),
			card(T('Absent'), absent.length, absent.length ? 'muted' : ''),
			card(T('Strangers'), events.filter(e => !e.person).length, ''),
		)

		const table = el('table', { class: 'fa-table' },
			el('thead', {}, el('tr', {},
				el('th', {}, ''), el('th', {}, T('Name')), el('th', {}, T('Arrived')),
				el('th', {}, T('Last seen')), el('th', {}, T('Rooms')), el('th', {}, T('Sightings')))),
			el('tbody', {}, rows.length ? rows.map(r => {
				const d = new Date(r.first.ts * 1000)
				const isLate = d.getHours() * 60 + d.getMinutes() > startMin
				return el('tr', {},
					el('td', {}, thumb(r.first)),
					el('td', { class: 'fa-name' }, r.person),
					el('td', {}, el('span', { class: 'fa-badge ' + (isLate ? 'fa-badge--late' : 'fa-badge--ok') }, hhmm(r.first.ts))),
					el('td', {}, hhmm(r.last.ts)),
					el('td', {}, [...r.rooms].join(', ')),
					el('td', {}, r.count))
			}) : el('tr', {}, el('td', { colspan: 6, class: 'fa-empty' }, T('Nobody recognised on this day yet')))),
		)

		const absentBox = absent.length
			? el('div', { class: 'fa-absent' }, el('h3', {}, T('Not seen')), el('div', { class: 'fa-chips' }, absent.map(p => el('span', { class: 'fa-chip' }, p))))
			: null

		return [cards, table, absentBox]
	}

	function card(label, value, mod) {
		return el('div', { class: 'fa-card' + (mod ? ' fa-card--' + mod : '') },
			el('div', { class: 'fa-card__value' }, value), el('div', { class: 'fa-card__label' }, label))
	}

	function renderEvents(events) {
		return el('table', { class: 'fa-table' },
			el('thead', {}, el('tr', {},
				el('th', {}, ''), el('th', {}, T('Time')), el('th', {}, T('Name')),
				el('th', {}, T('Room')), el('th', {}, T('Camera')), el('th', {}, T('Match')))),
			el('tbody', {}, events.length ? events.map(e => el('tr', {},
				el('td', {}, thumb(e)),
				el('td', {}, hhmmss(e.ts)),
				el('td', { class: e.person ? 'fa-name' : 'fa-unknown' }, e.person || T('Unknown')),
				el('td', {}, e.room),
				el('td', {}, e.camera),
				el('td', {}, e.person ? Math.round(e.score * 100) + '%' : '–')))
			: el('tr', {}, el('td', { colspan: 6, class: 'fa-empty' }, T('No events')))))
	}

	function renderStrangers(events) {
		const list = events.filter(e => !e.person)
		if (!list.length) return el('p', { class: 'fa-empty' }, T('No strangers on this day'))
		return el('div', { class: 'fa-grid' }, list.map(e => el('figure', { class: 'fa-stranger' },
			thumb(e), el('figcaption', {}, hhmmss(e.ts) + ' · ' + e.room))))
	}

	function exportCsv() {
		const esc = v => '"' + String(v ?? '').replace(/"/g, '""') + '"'
		let lines
		if (state.tab === 'summary') {
			lines = [[T('Name'), T('Date'), T('Arrived'), T('Last seen'), T('Rooms'), T('Sightings')]]
			for (const r of summarize(filtered())) {
				lines.push([r.person, state.date, hhmmss(r.first.ts), hhmmss(r.last.ts), [...r.rooms].join('; '), r.count])
			}
		} else {
			lines = [[T('Date'), T('Time'), T('Name'), T('Room'), T('Camera'), T('Match')]]
			for (const e of filtered().slice().reverse()) {
				lines.push([state.date, hhmmss(e.ts), e.person || T('Unknown'), e.room, e.camera, e.person ? e.score.toFixed(2) : ''])
			}
		}
		const blob = new Blob(['﻿' + lines.map(l => l.map(esc).join(',')).join('\r\n')], { type: 'text/csv;charset=utf-8' })
		const a = el('a', { href: URL.createObjectURL(blob), download: 'attendance-' + state.tab + '-' + state.date + '.csv' })
		document.body.append(a)
		a.click()
		setTimeout(() => { URL.revokeObjectURL(a.href); a.remove() }, 1000)
	}

	// ---------------------------------------------------------------- shell
	function render() {
		const events = filtered()
		const body = document.getElementById('fa-body')
		body.replaceChildren(...[].concat(
			state.tab === 'summary' ? renderSummary(events)
				: state.tab === 'events' ? renderEvents(events)
					: renderStrangers(events)).filter(Boolean))

		const roomSel = document.getElementById('fa-room')
		const rooms = [...new Set(state.events.map(e => e.room))].sort()
		roomSel.replaceChildren(el('option', { value: '' }, T('All rooms')),
			...rooms.map(r => el('option', { value: r, selected: r === state.room }, r)))

		document.querySelectorAll('.fa-tab').forEach(b => b.classList.toggle('fa-tab--active', b.dataset.tab === state.tab))
	}

	function mount() {
		const root = document.getElementById('fa-root')
		if (!root) return
		const tab = (id, label) => el('button', { class: 'fa-tab', 'data-tab': id, onclick: () => { state.tab = id; render() } }, label)

		root.append(
			el('header', { class: 'fa-header' },
				el('h2', {}, T('Attendance')),
				el('div', { class: 'fa-tabs' }, tab('summary', T('Summary')), tab('events', T('All events')), tab('strangers', T('Strangers'))),
			),
			el('div', { class: 'fa-toolbar' },
				el('button', { class: 'fa-btn', title: T('Previous day'), onclick: () => shiftDay(-1) }, '‹'),
				el('input', { type: 'date', id: 'fa-date', value: state.date, onchange: e => { state.date = e.target.value || todayStr(); refresh() } }),
				el('button', { class: 'fa-btn', title: T('Next day'), onclick: () => shiftDay(1) }, '›'),
				el('button', { class: 'fa-btn', onclick: () => setDate(todayStr()) }, T('Today')),
				el('select', { id: 'fa-room', onchange: e => { state.room = e.target.value; render() } }),
				el('input', { type: 'search', placeholder: T('Search name…'), oninput: e => { state.search = e.target.value; render() } }),
				el('label', { class: 'fa-start', title: T('Arrivals after this time are marked late') },
					T('Work starts'),
					el('input', { type: 'time', value: state.workStart, onchange: e => { state.workStart = e.target.value || '09:00'; save('workStart', state.workStart); render() } })),
				el('button', { class: 'fa-btn', onclick: exportCsv }, T('Export CSV')),
				el('span', { id: 'fa-status', class: 'fa-status' }),
			),
			el('div', { id: 'fa-body' }),
		)
		refresh()
		// live view: refresh every 30 s while looking at today
		state.timer = setInterval(() => { if (state.date === todayStr() && !document.hidden) refresh() }, 30000)
	}

	function setDate(d) {
		state.date = d
		document.getElementById('fa-date').value = d
		refresh()
	}
	function shiftDay(n) {
		const [y, m, d] = state.date.split('-').map(Number)
		const dt = new Date(y, m - 1, d + n)
		setDate(dt.getFullYear() + '-' + pad(dt.getMonth() + 1) + '-' + pad(dt.getDate()))
	}

	if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount)
	else mount()
})()
