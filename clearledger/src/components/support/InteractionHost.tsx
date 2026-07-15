/**
 * InteractionHost — оркестратор вспомогательной области «Взаимодействие».
 *
 * Рендерит обе подачи; активна одна по SupportContext.interactionMode:
 *  • RightDock (mode='dock')  — пристыкованная панель справа (двигает контент).
 *  • InteractionModal (mode='modal') — окно поверх всего (портал, вне потока).
 *
 * Монтируется как flex-сосед рабочей области в MainLayout: док занимает место в
 * ряду, модалка уходит в портал и от позиции в дереве не зависит.
 */
import { RightDock } from './RightDock'
import { InteractionModal } from './InteractionModal'

export default function InteractionHost() {
  return (
    <>
      <RightDock />
      <InteractionModal />
    </>
  )
}
