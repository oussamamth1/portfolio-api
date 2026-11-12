import { IsInt, IsOptional, IsString, Max, Min } from 'class-validator';

export class CreateLanguageDto {
  @IsString()
  language!: string;

  @IsInt()
  @Min(0)
  @Max(100)
  level!: number;

  @IsOptional()
  @IsInt()
  sort_order?: number;
}
