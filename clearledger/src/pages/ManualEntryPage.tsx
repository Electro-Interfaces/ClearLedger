import { ManualEntryForm } from '@/components/manual/ManualEntryForm'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

export function ManualEntryPage() {
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-bold tracking-tight">Ручной ввод</h1>

      <Tabs defaultValue="new">
        <TabsList>
          <TabsTrigger value="new">Новая запись</TabsTrigger>
          <TabsTrigger value="correction">Корректировка</TabsTrigger>
          <TabsTrigger value="note">Примечание</TabsTrigger>
        </TabsList>

        <TabsContent value="new" className="mt-4">
          <div className="max-w-2xl">
            <ManualEntryForm entryType="new" />
          </div>
        </TabsContent>

        <TabsContent value="correction" className="mt-4">
          <div className="max-w-2xl">
            <ManualEntryForm entryType="correction" />
          </div>
        </TabsContent>

        <TabsContent value="note" className="mt-4">
          <div className="max-w-2xl">
            <ManualEntryForm entryType="note" />
          </div>
        </TabsContent>
      </Tabs>
    </div>
  )
}
