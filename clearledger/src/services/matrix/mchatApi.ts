// REST к бэкенду чата экосистемы (/api/mchat/*): сессия, группы, личка, папки, публичные, люди.
import { get, post, patch, del } from '../apiClient'
import type { ChatSession } from './types'

export interface GroupRoom { roomId: string; title: string; ownerId?: string; isPublic: boolean }
export interface ChatFolderDto { id: string; name: string; roomIds: string[]; order: number }
export interface Person { id: string; name: string; email: string }

export function getSession(): Promise<ChatSession> {
  return get<ChatSession>('/api/mchat/session')
}

export async function listGroups(): Promise<GroupRoom[]> {
  return (await get<{ rooms: GroupRoom[] }>('/api/mchat/groups')).rooms
}
export function createGroup(title: string, participantIds: string[], isPublic: boolean): Promise<GroupRoom> {
  return post<GroupRoom>('/api/mchat/groups', { title, participantIds, isPublic })
}
export function openDm(userId: string): Promise<{ roomId: string }> {
  return post<{ roomId: string }>('/api/mchat/dm', { userId })
}
export async function listPublic(): Promise<GroupRoom[]> {
  return (await get<{ rooms: GroupRoom[] }>('/api/mchat/public')).rooms
}
export function joinRoom(roomId: string): Promise<{ roomId: string; joined: boolean }> {
  return post('/api/mchat/join', { roomId })
}

export async function listFolders(): Promise<ChatFolderDto[]> {
  return (await get<{ folders: ChatFolderDto[] }>('/api/mchat/folders')).folders
}
export function createFolder(name: string, roomIds: string[]): Promise<ChatFolderDto> {
  return post<ChatFolderDto>('/api/mchat/folders', { name, roomIds })
}
export function updateFolder(id: string, body: { name?: string; roomIds?: string[] }): Promise<{ ok: boolean }> {
  return patch(`/api/mchat/folders/${id}`, body)
}
/** Переупорядочивание: backend принимает {order:[...]} на любом id папки. */
export function reorderFolders(anyFolderId: string, order: string[]): Promise<{ ok: boolean }> {
  return patch(`/api/mchat/folders/${anyFolderId}`, { order })
}
export function deleteFolder(id: string): Promise<void> {
  return del(`/api/mchat/folders/${id}`)
}

export async function searchPeople(q: string): Promise<Person[]> {
  return (await get<{ people: Person[] }>('/api/mchat/people', { q })).people
}
