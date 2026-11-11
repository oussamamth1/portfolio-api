import {
  IsArray,
  IsBoolean,
  IsInt,
  IsOptional,
  IsString,
  IsUrl,
} from 'class-validator';

export class CreateProjectDto {
  @IsString()
  title!: string;

  @IsOptional()
  @IsString()
  company?: string;

  @IsOptional()
  @IsString()
  period?: string;

  @IsOptional()
  @IsString()
  location?: string;

  @IsOptional()
  @IsString()
  description?: string;

  @IsOptional()
  @IsString()
  icon_key?: string;

  @IsOptional()
  @IsString()
  category?: string;

  @IsOptional()
  @IsArray()
  @IsString({ each: true })
  technologies?: string[];

  @IsOptional()
  @IsArray()
  @IsString({ each: true })
  highlights?: string[];

  @IsOptional()
  @IsString()
  status?: string;

  @IsOptional()
  @IsUrl()
  github_url?: string;

  @IsOptional()
  @IsUrl()
  app_store_url?: string;

  @IsOptional()
  @IsUrl()
  play_store_url?: string;

  @IsOptional()
  @IsString()
  video_id?: string;

  @IsOptional()
  @IsUrl()
  image_url?: string;

  @IsOptional()
  @IsBoolean()
  portrait?: boolean;

  @IsOptional()
  @IsInt()
  sort_order?: number;
}
