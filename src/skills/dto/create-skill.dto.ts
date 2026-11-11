import { IsInt, IsOptional, IsString, Max, Min } from 'class-validator';

export class CreateSkillDto {
  @IsString()
  category!: string;

  @IsOptional()
  @IsString()
  icon_key?: string;

  @IsString()
  subject!: string;

  @IsInt()
  @Min(0)
  @Max(100)
  level!: number;

  @IsOptional()
  @IsInt()
  sort_order?: number;
}
