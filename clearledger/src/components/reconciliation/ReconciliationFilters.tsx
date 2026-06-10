/**
 * Панель фильтров сверки
 */

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Filter, ChevronDown, ChevronRight, X } from 'lucide-react';

interface ReconciliationFiltersProps {
  filtersOpen: boolean;
  onFiltersOpenChange: (open: boolean) => void;
  stationFilter: string;
  onStationFilterChange: (value: string) => void;
  statusFilter: string;
  onStatusFilterChange: (value: string) => void;
  fuelFilter: string;
  onFuelFilterChange: (value: string) => void;
  searchCard: string;
  onSearchCardChange: (value: string) => void;
  onClearFilters: () => void;
  uniqueStations: [number, string][];
  uniqueFuels: string[];
}

export function ReconciliationFilters({
  filtersOpen,
  onFiltersOpenChange,
  stationFilter,
  onStationFilterChange,
  statusFilter,
  onStatusFilterChange,
  fuelFilter,
  onFuelFilterChange,
  searchCard,
  onSearchCardChange,
  onClearFilters,
  uniqueStations,
  uniqueFuels
}: ReconciliationFiltersProps) {
  return (
    <Card className="bg-card border-border">
      <Collapsible open={filtersOpen} onOpenChange={onFiltersOpenChange}>
        <CollapsibleTrigger asChild>
          <CardHeader className="cursor-pointer hover:bg-secondary/50 transition-colors py-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-foreground text-sm flex items-center gap-2">
                <Filter className="h-4 w-4" />
                Фильтры
              </CardTitle>
              {filtersOpen ? (
                <ChevronDown className="h-4 w-4 text-muted-foreground" />
              ) : (
                <ChevronRight className="h-4 w-4 text-muted-foreground" />
              )}
            </div>
          </CardHeader>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <CardContent className="pt-0 pb-4">
            <div className="grid grid-cols-2 md:grid-cols-2 lg:grid-cols-5 gap-3">
              <Select value={stationFilter} onValueChange={onStationFilterChange}>
                <SelectTrigger className="bg-background border-border">
                  <SelectValue placeholder="Станция" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Все станции</SelectItem>
                  <SelectItem value="discrepancies" className="text-red-600 dark:text-red-400">Расхождения</SelectItem>
                  {uniqueStations.map(([id, name], idx) => (
                    <SelectItem key={`station_${id}_${idx}`} value={String(id)}>{name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>

              <Select value={statusFilter} onValueChange={onStatusFilterChange}>
                <SelectTrigger className="bg-background border-border">
                  <SelectValue placeholder="Статус" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Все статусы</SelectItem>
                  <SelectItem value="matched">OK</SelectItem>
                  <SelectItem value="only_corp">Только Corp</SelectItem>
                  <SelectItem value="only_tf">Только TF</SelectItem>
                  <SelectItem value="mismatch">Расхождение</SelectItem>
                </SelectContent>
              </Select>

              <Select value={fuelFilter} onValueChange={onFuelFilterChange}>
                <SelectTrigger className="bg-background border-border">
                  <SelectValue placeholder="Топливо" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Все виды</SelectItem>
                  {uniqueFuels.map((fuel, idx) => (
                    <SelectItem key={`fuel_${fuel}_${idx}`} value={fuel}>{fuel}</SelectItem>
                  ))}
                </SelectContent>
              </Select>

              <Input
                placeholder="Номер карты..."
                value={searchCard}
                onChange={(e) => onSearchCardChange(e.target.value)}
                className="bg-background border-border"
              />

              <Button
                variant="outline"
                size="sm"
                onClick={onClearFilters}
                
              >
                <X className="h-4 w-4 mr-2" />
                Сброс
              </Button>
            </div>
          </CardContent>
        </CollapsibleContent>
      </Collapsible>
    </Card>
  );
}
